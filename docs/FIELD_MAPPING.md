# FIELD_MAPPING.md — RDA 지침 컬럼별 해외 비교가능성 (STEP 2)

> 작성일: 2026-08-18 · 상태: STEP 2 (조사·문서화 단계)
> 근거: RDA API 실호출(2026-08-18, 35,975건)로 확인한 실제 컬럼 구조.

## 0. 목적

RDA 「수출농산물 농약안전사용지침」의 **실제 컬럼**을 기준으로, 각 컬럼이
어느 해외 Source(Japan / EU / Codex)와 **어떤 수준으로 비교 가능한가**를 확정한다.
이는 향후 comparison engine이 "무엇을 deterministic code로 비교하고, 무엇을 매핑/보류/제외할지"의 근거가 된다.

## 1. RDA 실제 컬럼 (재확인)

`국가, 작목, 용도, 적용병해충, 품목명, 작용기작, 상표명, 횟수, 약량, 외국, 한국` (총 11개)

- `외국` = 수입국 MRL (RDA가 캐시한 값), `한국` = 국내 지침 MRL. 둘 다 파이프 배열(성분별).
- **부재**: CAS ✗, 영문명 ✗, 학명 ✗, PHI ✗, 희석배수 ✗, 시행일 ✗, 등록상태 ✗.

## 2. 비교가능성 매트릭스

범례: **O** = 구조적으로 비교 가능(대체로 deterministic) · **△** = 국가별/조건부 가능(정규화·매핑 필요) ·
**X** = 해당 Source에 대응 개념 없음 · 비교대상 아님

| # | RDA 필드 | 의미 | Japan | EU | Codex | 종합 비교가능성 | 비교 방식 |
|---|---|---|---|---|---|---|---|
| 1 | `외국`/`한국` (MRL, 성분별 배열) | 잔류허용기준 | O | O | O | **높음** | **deterministic 숫자비교** (전처리: 성분 분해) |
| 2 | `품목명` (유효성분+제형, 한글) | 농약 식별 | △ | △ | △ | 매핑 필요 | pesticide_master 경유 (CAS/식별자) |
| 3 | `작목` | 작물 | △ | △ | △ | 국가별 확인 | commodity_master 경유 (코드 매핑) |
| 4 | `적용병해충` | 대상 병해충 | △ | X | X | 대부분 UNMAPPED | 해외 MRL은 병해충 단위 아님 |
| 5 | `횟수` | 사용 횟수 | △ | △ | X | 국가별 확인 | 등록/라벨 정보 측, MRL DB엔 통상 없음 |
| 6 | `약량` | 사용량/dose | △ | △ | X | 국가별 확인 | 자유텍스트 정규화 후 조건부 |
| 7 | (PHI) | 수확전안전사용기간 | △ | △ | X | 국가별 확인 | **RDA엔 컬럼부재** → 해외 등록정보서만 |
| 8 | `작용기작` | MoA 코드 | △ | △ | X | 참고용 | 식별 보조, 비교 판정 아님 |
| 9 | `용도` | 살충/살균 등 | 참고 | 참고 | 참고 | 낮음 | 필터/맥락용 |
| 10 | `상표명` | 제품 상표 | X | X | X | **비교대상 아님** | 국내 상표, 대응 없음 |

## 3. 필드별 상세

### 3.1 MRL (`외국`/`한국`) — 비교의 핵심, deterministic

**전처리 (필수):**
1. `품목명`에서 제형 `(액상수화제)` 등을 분리하고, 점(`.`)으로 유효성분 리스트를 만든다.
2. `외국`/`한국` 파이프 배열을 성분 리스트와 **위치 정렬**한다.
   - 예: 품목명 `A.B.C` → `한국 "0.05|0.3|0.1"` → `{A:0.05, B:0.3, C:0.1}`.
   - `-` = 미설정 → `None` (0과 구분).
3. 각 유효성분을 pesticide_master로 식별 → 해외 Source(EU/Japan/Codex)의 MRL을 조회.
4. **작물(commodity)** 을 commodity_master로 매핑 → 동일 commodity 기준으로 비교.

**비교 규칙 (deterministic, §5 — LLM 사용 금지):**
- RDA `외국`(캐시) vs 해외 라이브값 → 다르면 `FOREIGN_CHANGED` 후보.
- 국내 `한국` vs 해외 라이브값 →
  - 같으면 `MATCH`
  - 국내가 더 엄격(작은 값)이면 `RDA_STRICTER`
  - 국내가 더 높으면 `RDA_HIGHER` (수출 리스크 → Severity 상향)
  - 해외 기준 없음이면 `NO_FOREIGN_STANDARD`
- 단위/자릿수/`ppm` 정규화, 반올림 정책, Codex/Default/LOQ/Temporary/Exemption 구분(§2-A)을 코드로 처리.
- **주의:** MRL이 "안 보임"은 삭제가 아닐 수 있다 → §MONITORING의 Change/Failure 구분 적용, 정상수집 확인 후에만 `POSSIBLE_DELETION`.

### 3.2 농약 식별 (`품목명`) — 매핑 선행

- RDA엔 CAS/영문명이 없어 **한글 유효성분명 → pesticide_master → CAS/영문/각국 식별자** 매핑이 선행되어야 한다.
- 매핑 우선순위(§10): CAS Number > 공식 identifier(EU/Japan/Codex) > 영문 common name > alias 문자열.
- Codex는 안정적 `p_id`(예: Fludioxonil=211) 보유 → `Codex_identifier`로 직접 활용.
- 매핑 상태(§12): `EXACT / IDENTIFIER_MATCH / ALIAS_MATCH / MANUAL_MAPPING / AI_SUGGESTED / AMBIGUOUS / UNMAPPED`.
  - `AI_SUGGESTED`는 담당자 승인 전까지 정식 매핑으로 쓰지 않는다.
- 혼합제(다성분)는 성분별로 분해해 각각 매핑한다.

### 3.3 작물 (`작목`) — 임의 매칭 금지

- 국가별 commodity 분류체계가 다르므로(EU code / Codex CCN / Japan 食品分類), **임의 매칭 금지**(§11).
- commodity_master 경유: `RDA_name → {EU_code, Codex_code, Japan_name/code}`.
- 매핑 불가/모호 시 `UNMAPPED`/`AMBIGUOUS`로 두고 비교를 보류(REVIEW_REQUIRED)한다.
- 작물군(parent_group) 단위 대응이 필요한 경우가 있어 세부작물/상위군을 함께 관리.
- **STEP4 실증**: ① Codex는 사과·배를 `Pome fruits (group)`로만 제공(그룹매핑 필수).
  ② EU는 `Strawberry`(0632010, 허브침출)와 `(b) strawberries`(0152000, 과일) 두 product 존재 →
  이름 매칭 시 오값(0.05\*) 획득. **반드시 코드 기반 매핑**. 상세: [STEP4_VALIDATION.md](STEP4_VALIDATION.md)

### 3.4 사용조건 (`횟수`, `약량`, PHI)

- 해외 **MRL DB에는 통상 사용조건이 없다**. 사용조건은 각국 **등록/라벨 정보**에 존재.
  - EU: 제품승인은 회원국별 → EU 중앙 MRL DB로는 부분만.
  - Japan: MRL DB(jpn-pesticides-database)엔 없음 → JMAFF/ACIS 등록정보 별도.
  - Codex: 사용조건 대상 아님.
- `약량`은 `"740mL,(0.8L/10a)"`, `"50g/상자"` 등 자유텍스트 → dose/면적환산/포장단위 파싱 규칙 필요.
- **PHI는 RDA 지침 자체에 컬럼이 없다** → 비교하려면 별도 국내 PHI 소스가 필요(향후 조사).
- 이 영역의 비교는 대부분 `REVIEW_REQUIRED` 또는 `USAGE_CHANGED` 후보 수준으로 관리하고, 확정은 보류.

### 3.5 비교대상 아님 / 참고

- `상표명`: 국내 상표 → 해외 대응 없음. 비교하지 않음.
- `작용기작`(MoA): 식별/검증 보조. 판정 근거로 쓰지 않음.
- `용도`, `적용병해충`: 필터·맥락. 해외 MRL은 병해충 단위가 아니므로 `적용병해충`은 대체로 `UNMAPPED`.

## 4. 판정·중요도 연결 (§3·§4)

항목별 상태를 개별 관리하고, 전체 상태는 그중 최악으로 롤업한다. 예(§3):

```
Japan / Strawberry / Fludioxonil
  MRL:        MATCH
  등록상태:    MATCH
  사용횟수:    REVIEW_REQUIRED
  PHI:        MATCH
  적용병해충:  UNMAPPED
  전체상태:    REVIEW_REQUIRED
```

- 규정 상태(§4): `MATCH / RDA_STRICTER / RDA_HIGHER / FOREIGN_CHANGED / UPCOMING_CHANGE /
  REGISTRATION_CHANGED / USAGE_CHANGED / TARGET_CHANGED / NO_FOREIGN_STANDARD / UNMAPPED / AMBIGUOUS / REVIEW_REQUIRED`.
- Severity(§4): `CRITICAL / HIGH / MEDIUM / LOW / INFO`. (예: `RDA_HIGHER`+수출대상국 = HIGH 이상)

## 5. deterministic vs LLM 경계 (§5 — 매우 중요)

| 반드시 deterministic code | LLM 허용 (결과에 `AI_ANALYZED` 표기) |
|---|---|
| MRL 숫자 비교 (단위/자릿수 정규화 포함) | 자연어 규정문 요약 |
| 등록여부/등록상태 판정 | SPS 통보문 분석 |
| 날짜·시행일 비교, freshness | 변경내용 설명문 생성 |
| 사용횟수 등 수치 비교 | 매핑 후보 추천 (담당자 승인 전제) |
| 상태/Severity 롤업 | 담당자용 설명문 생성 |

- **LLM 결과만으로 규정 변경/일치를 확정하지 않는다.** 확정은 항상 deterministic 결과로.
- LLM이 만든 매핑은 `AI_SUGGESTED` → 담당자 승인 후에만 정식 매핑.

## 6. 종합 비교가능성 결론

| 우선순위 | 비교 항목 | Source 조합 | 신뢰수준 |
|---|---|---|---|
| 1 | **MRL 숫자** | RDA ↔ Japan / EU / Codex | 높음 (deterministic) — **PoC 우선 대상** |
| 2 | 등록/승인 상태 | RDA(없음) ↔ EU active substance / (Japan 별도) | 중간 (해외측만, 국내 컬럼 부재) |
| 3 | 사용조건(횟수/약량/PHI) | 대부분 등록정보 측 | 낮음 (REVIEW 중심) |
| — | 상표명·용도·병해충·MoA | — | 비교대상 아님/참고 |

→ **PoC 검증(STEP 4)은 MRL 숫자 비교를 중심으로** 딸기/사과/배/포도 + 농약 10~20종에 대해 RDA↔Japan/EU/Codex로 수행한다.

---
*본 문서는 STEP 2 산출물이다. PHI 국내 소스, EU/Japan 등록·사용조건 스키마 등 ⚠️ 미확인 항목은 구현 전 재확인한다.*
