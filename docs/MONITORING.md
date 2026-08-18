# MONITORING.md — 시스템 상태·수집장애 탐지 전략 (STEP 3)

> 작성일: 2026-08-18 · 상태: STEP 3 (설계·문서화 단계)
> 핵심 철학(§36): "변경이 없다"가 아니라 **"최신 정보를 정상적으로 확인했고, 그 결과 변경이 없다"** 를 증명한다.
> 최신성 확인이 불가능하면 "이상 없음"이 아니라 **"최신성 확인 필요"** 로 표시한다.

## 0. 규정 상태 ≠ 시스템 상태 (§35)

담당자는 두 질문을 **절대 혼동하면 안 된다**:
- (규정) 규정에 문제가 없는가?  ↔  (시스템) 데이터를 제대로 가져오고 있는가?

따라서 System Health는 comparison 결과와 **완전히 분리된 축**으로 관리하고, 대시보드 최상단에 나란히 노출한다.

---

## 1. Source Health 상태 모델 (§17)

| 상태 | 의미 | 대표 진입조건 |
|---|---|---|
| `HEALTHY` | 정상 수집 + 검증 통과 | 아래 §2 3계층 검증 모두 통과 |
| `WARNING` | 수집됐으나 이상 징후 | record 급감/급증, null 급증 등 이상치(§4) |
| `STALE` | 예상 갱신주기 초과 | `now - last_success > expected_update_interval × 계수`(§5) |
| `FAILED` | 수집 자체 실패 | 네트워크/타임아웃/HTTP 4xx·5xx, 재시도 소진(§7) |
| `PARSER_ERROR` | 수집됐으나 파싱 실패 | 기대 selector/필드 부재, 파싱 예외 |
| `SOURCE_UNAVAILABLE` | 원본 사이트 접근 불가 | DNS/연결 실패, 지속적 503 |
| `SCHEMA_CHANGED` | 구조 변경 감지 | 컬럼/DOM fingerprint 불일치(§3) |
| `AUTH_ERROR` | 인증 실패 | 401/403, 키 만료 |
| `UNKNOWN` | 판단 불가 | 최초 수집 전, 상태 미확정 |

**상태 우선순위(동시 발생 시):** `AUTH_ERROR`/`SOURCE_UNAVAILABLE`/`FAILED` > `PARSER_ERROR`/`SCHEMA_CHANGED` > `WARNING` > `STALE` > `HEALTHY`.

---

## 2. 수집 성공 판정 — 3계층 검증 (§19)

**HTTP 200 = 성공으로 보지 않는다.** 다음 3계층을 모두 통과해야 `HEALTHY` 후보.

### (A) Response check
- HTTP status (2xx)
- content-type (기대: JSON/XML/CSV/HTML 일치)
- 응답 크기 (0/비정상 소형 아님)
- encoding (UTF-8 등 기대 인코딩)

### (B) Content check
- 기대 제목/필수 element 존재
- 필수 field 존재 (예: RDA `국가/작목/품목명/외국/한국`)
- record count > 0 및 기대 범위
- 주요 column 존재

### (C) Schema check (§19·§30)
- **컬럼/DOM fingerprint**를 저장하고 매 수집 시 비교.
  - 예: 기존 `pesticide/commodity/mrl` → 신규 `chemical_name/crop/limit` 로 바뀌면 `SCHEMA_CHANGED`.
  - 웹 crawling source는 주요 selector 집합의 fingerprint(해시)를 저장.
- **selector가 사라졌으면 `PARSER_ERROR` 또는 `SCHEMA_CHANGED`.**
- **Claude/자동화가 새 구조를 추측해 parser를 임의 수정하지 않는다(§30).** 담당자 알림 후 사람이 반영.

---

## 3. Schema / 사이트 변경 감지 (§30)

- 저장: `schema_hash`(구조화 소스=컬럼셋 해시 / 웹=selector fingerprint 해시).
- 비교: 직전 성공 수집의 `schema_hash`와 대조 → 불일치 시 `SCHEMA_CHANGED`.
- fingerprint 대상(웹 source): 결과 표의 헤더 텍스트, 핵심 셀 selector 경로, 페이지 주요 anchor.
- `SCHEMA_CHANGED`는 자동 판정을 멈추고 **사람 검토**로 넘긴다 (오탐지 시 규정 오판 위험이 크므로).

---

## 4. 이상치 탐지 (§20)

정상 HTTP여도 다음 조건이면 `WARNING` 또는 `PARSER_ERROR`:

| 이상 | 조건(예) | 판정 |
|---|---|---|
| record count 급감 | `records < previous × 0.5` (예: EU 120,000 → 350) | `WARNING`→검토 (심하면 `PARSER_ERROR`) |
| record count 급증 | `records > previous × 2` | `WARNING` |
| 필수 field null 급증 | null 비율이 baseline 대비 급등 | `WARNING`/`PARSER_ERROR` |
| 특정 국가 데이터 전체 소실 | 기대 국가 record = 0 | `WARNING` |
| 특정 pesticide 대량 소실 | 성분별 record 급감 | `WARNING` |
| content length 급감 | 응답 바이트 급감 | `WARNING` |

- 급감/급증 임계(계수 0.5/2 등)는 Source별 변동성에 맞게 조정하고 `source_health`에 baseline 저장.

---

## 5. Freshness (§21)

각 데이터에 대해:

| Freshness | 조건 |
|---|---|
| `FRESH` | 최근 정상수집 + 공식 데이터 최신 확인 (`now - last_success ≤ interval`) |
| `AGING` | 정상 수집됐으나 일정 경과 (`interval < 경과 ≤ interval × 계수`) |
| `STALE` | 예상 갱신주기 초과 (`경과 > interval × 계수`) |
| `UNKNOWN` | 최신 여부 판단 불가 (최초 수집 전, 소스 상태 불명) |

- `expected_update_interval` (초기값, ⚠️ 실 주기 확정 후 조정):
  - **RDA**: 지침 개정 시(비정기) — UDDI/데이터셋 기준일 변경 감시.
  - **EU**: 일 단위(포털 메타 `daily` 실측).
  - **Japan**: 부정기(대략 월). 최종갱신일(お知らせ) 파싱으로 보정.
  - **Codex**: 연 단위(JMPR/CCPR).
  - **WTO ePing**: 상시(일 단위 폴링).
- **비교결과 옆에 항상 Freshness를 병기**한다(§21·§36).

---

## 6. Fail-safe — 실패를 최신처럼 표시 금지 (§22)

- 오늘 수집이 실패하면 **기존 값을 최신값처럼 표시하지 않는다.**
- 화면 표기 예:
  ```
  ⚠ 일본 MRL 데이터 최신성 확인 필요
  마지막 정상 확인: 2026-08-11
  오늘 수집: 실패
  현재 비교결과는 2026-08-11 데이터 기준
  ```
- 모든 비교결과에 반드시 병기(§36): `Source / Source 상태 / 마지막 성공 수집일 / 데이터 기준일 / 공식 시행일 / 비교일`.

---

## 7. 비교결과 신뢰도 (§23)

comparison 결과에 데이터 신뢰상태를 결합한다.

| 예 | 표기 |
|---|---|
| 정상 | `Comparison: MATCH · Data confidence: HIGH · Source: HEALTHY` |
| 위험 | `Comparison: MATCH · Data confidence: LOW · Source: STALE` |

- Data confidence 매핑(초안): `HEALTHY+FRESH → HIGH`, `WARNING/AGING → MEDIUM`, `STALE/PARSER_ERROR/FAILED → LOW`.
- **"MATCH"라도 Source가 STALE이면 담당자를 안심시키지 않는다** — LOW로 표시.

---

## 8. Change Detection vs Failure Detection 분리 (§27)

record가 안 보일 때 **즉시 "삭제"로 판단하지 않는다.** 다음 순서로 원인 규명:

1. 사이트 수집 실패인가? → `FAILED`/`SOURCE_UNAVAILABLE`
2. parser 실패인가? → `PARSER_ERROR`/`SCHEMA_CHANGED`
3. 정상 수집 + 검증 통과했는데 해당 record만 없는가? → **이때만** `POSSIBLE_DELETION` (규정 변경 후보)

→ 수집/파싱 건강이 확인되지 않은 상태의 "없음"은 규정 변경으로 승격하지 않는다.

---

## 9. 재시도 정책 (§29)

- 일시적 네트워크 오류만 재시도, **무한 retry 금지.**
- 정책(초안): 1차 실패 → 5분 후 → 30분 후 → 최종 실패 → 담당자 알림.
- `AUTH_ERROR`/`SCHEMA_CHANGED`는 재시도 대상 아님(구성/구조 문제) → 즉시 알림.
- `collection_runs.retry_count`에 기록.

---

## 10. Source별 적용표

| Source | 수집방식 | 성공조건 특이점 | 주요 실패/오류 | stale 기준 | 안정성 |
|---|---|---|---|---|---|
| **RDA** | odcloud API | `totalCount≈35,975` 급변 감시, 11컬럼 존재 | AUTH_ERROR(키), UDDI 변경 | 개정 비정기 → 기준일 변화 감시 | 높음 |
| **EU** | Open Data API/다운로드 | distribution 스키마 필드 존재, daily 갱신 확인 | API 스키마 변경, rate-limit | >2일 무갱신 | 높음 |
| **Japan** | 폼 crawling | selector fingerprint 일치, 결과행>0, 備考 시행일 파싱 | PARSER_ERROR, SCHEMA_CHANGED | >45일 무갱신(월주기 가정) | 낮음 |
| **Codex** | p_id 스크레이핑 | 상세표 컬럼 fingerprint, p_id 순회 완주 | PARSER_ERROR, 페이지 구조 변경 | >약 400일(연주기) | 낮음 |
| **WTO** | Data Portal API/XLSX | 통보문 필드 존재, 무료키 유효 | AUTH_ERROR(키), 스키마 변경 | >2일 무폴링 | 중간 |

- **낮음(Japan/Codex)** 은 §30 fingerprint를 반드시 저장하고, 변경 시 자동판정 중단·사람검토로 넘긴다.

---

## 11. 저장 스키마 매핑 (§18·§28)

### `source_health` (Source 현재상태 스냅샷) — §18
`source_name, country, latest_attempt_at, last_success_at, last_failure_at, last_data_date,
expected_update_interval, consecutive_failures, HTTP_status, response_time, number_of_records,
previous_number_of_records, schema_hash, content_hash, collector_version, parser_version, status, status_message`

### `collection_runs` (모든 수집 로그) — §28
`run_id, source, started_at, finished_at, status, HTTP_status, records_received, records_valid,
records_invalid, schema_changed, error_type, error_message, retry_count`

### 원본 보존 `raw_snapshots` — §9
`source, URL, retrieved_at, HTTP_status, content_type, content_hash, file_hash, source_version,
effective_date, raw_file_path` → "2026-08-10에 이 값이 왜 이렇게 판정됐는가"를 재현 가능하게.

---

## 12. 알림 (§26) — 규정 알림과 시스템 알림 분리

- **규정 알림** 예: `[HIGH] 일본 딸기 Fludioxonil MRL 변경`
- **시스템 알림** 예:
  ```
  [HIGH] 일본 MHLW/CAA 데이터 수집 실패
  마지막 정상 수집: 2026-08-11 · 연속 실패: 3회
  현재 일본 관련 비교 결과의 최신성을 보장할 수 없음 — 담당자 확인 필요
  ```
- 시스템 이상(record 85% 급감 등)도 규정 변경과 **동등하게 알림 대상**(§25·§26).

---

## 13. 대시보드 반영 (§24·§35)

최상단 2개 요약을 나란히:
```
규정 상태            데이터 수집 상태
🟢 정상 352          🟢 정상 Source 4
🟡 확인필요 21       🟡 주의 Source 1
🔴 불일치 7          🔴 실패 Source 0
```
시스템 현황 표: `국가 | 데이터 | 상태 | 마지막 정상수집 | 마지막 시도 | 최신성`.

---

## 14. 검증 체크리스트 (본 문서 자체 검증)

- [ ] §17의 9개 상태 모두 진입조건이 정의되었는가
- [ ] HTTP 200을 성공으로 보지 않는 3계층 검증(§2)이 명시되었는가
- [ ] 이상치(§4)·Freshness(§5)·Fail-safe(§6)·Change vs Failure(§8) 규칙이 있는가
- [ ] Source별 적용표(§10)에 5개 Source가 개별 기준으로 있는가
- [ ] `source_health`/`collection_runs`/`raw_snapshots` 필드가 매핑되었는가

---
*본 문서는 STEP 3 산출물이다. `expected_update_interval`·이상치 임계·selector fingerprint 대상은 STEP 4 소규모 검증에서 실데이터로 보정한다.*
