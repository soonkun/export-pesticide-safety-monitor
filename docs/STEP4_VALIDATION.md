# STEP4_VALIDATION.md — 소규모 실데이터 비교 검증 (STEP 4)

> 작성일: 2026-08-18 · 상태: STEP 4 (실데이터 검증 완료)
> 목적: 실제 공식 소스에서 데이터를 **직접 수집**하여 RDA ↔ Japan/EU/Codex MRL 비교가
> deterministic하게 가능한지, commodity/pesticide 매핑이 실제로 어떻게 걸리는지를 검증한다.
> **모든 수치는 2026-08-18 실제 API/DB 응답에서 verbatim 추출한 값이다(추측·보간 없음).**

## 1. 검증 범위

- 작물: **딸기 · 사과 · 배 · 포도** (명세 STEP 4 지정)
- 농약: **Fludioxonil**(전 소스 완전 추적) + **Azoxystrobin**(기계판독 소스 교차확인)
- 소스: RDA(odcloud API) · Japan(jpn-pesticides-database) · Codex(FAO) · EU(DG SANTE Datalake API)
- 기준 케이스: 명세서 예시인 **Japan / Strawberry / Fludioxonil**.

## 2. 소스별 실제 접근 방법 (이번에 직접 성공한 방식)

### 2.1 RDA — odcloud API + 조건필터 (✅ 신규 확인)
`cond[<컬럼>::EQ]` 와 `cond[<컬럼>::LIKE]` **필터가 실제로 작동**한다(전체 스캔 불필요).
```
GET .../uddi:eacf...?perPage=50
    &cond[국가::EQ]=일본
    &cond[작목::EQ]=딸기
    &cond[품목명::LIKE]=플루디옥소닐
    &serviceKey=...
```
- 응답의 `matchCount` = 필터 결과 건수(예: 일본×딸기 = **407건**, 일본×포도 = 532건).
- **중요 실측**: 일본×사과 = 0건, 일본×배 = 0건 → RDA 지침은 **수출 대상 (국가×작목) 조합만** 포함한다.
  즉 "대일본 사과/배"는 지침에 아예 없음 → `NO_FOREIGN_STANDARD`가 아니라 **비교대상 자체가 없음**으로 처리해야 한다.
- MRL 셀에 `면제`(Exemption) 실제 등장(예: 폴리옥신디, 황).

### 2.2 EU — DG SANTE Datalake API (✅ 완전 확인, 인증키 불필요)
공식 파라미터는 EU가 배포한 API 문서 PDF(`Pesticides-APIs-V3.0.pdf`)에서 **직접 추출**했다.
- Base: `https://api.datalake.sante.service.ec.europa.eu/sante/pesticides/`
- 엔드포인트/파라미터(확인됨):
  | 엔드포인트 | 파라미터 | 용도 |
  |---|---|---|
  | `pesticide-residues-products` | `language`(필수), `format`, `product_id`, `product_parent_id`, `product_code`, `product_type_id`, `api-version=v3.0` | 작물(product) 목록 (총 **381개**) |
  | `product-current-mrl-all-residues` | `PRODUCT_ID`(필수), `format`, `api-version=v3.0` | 한 작물의 전체 잔류물 현행 MRL |
  | `active-substances` | `substance_id`, `substance_name`, `substance_status`, `approval_date`, `expiry_date`, `substance_category` … | 유효성분 등록/승인 상태 |
  | `pesticide-residues-mrls-download` | `language`(필수), `format` | 전량 flat file (>10MB) |
- 페이징: 응답 `{ "value":[...], "nextLink":"...&$after=<cursor>" }`, **page size 100**. 필터로 못 줄이는 엔드포인트는 nextLink 순회.
- MRL 레코드 필드: `PRODUCT_ID, PEST_RES_ID, MRL_VALUE, MRL_LOD, MRL_DISPLAY, PESTICIDE_RESIDUE_NAME, MRL_FOOTNOTE`.
  - `MRL_LOD="*"` + `MRL_DISPLAY="0.05*"` = **기본값/LOQ(특정 MRL 미설정)**.
- 작물코드 = EU Reg 396/2005 Annex I 코드: `0130010 Apples · 0130020 Pears · 0151010 Table grapes · 0152000 strawberries`.
- 간헐적 `HTTP 500`(일시적) → 재시도로 해결.

### 2.3 Japan — 검색 시스템 (✅ 상세 접근법 확인)
- 검색 결과행 DOM: `onclick="showDetail('<코드>','mn')"` — 예: **Fludioxonil = 코드 `079900`**.
- 상세 표: `Food types | Maximum residue limit(ppm) | Setting Basis | Remarks`.
  - Setting Basis 예: `Ab2011`, `Ad2018`(연도 포함 코드).
  - Remarks에 **시행일** 실제 기재: `"This MRL is applicable from April 26, 2024."`, `"Old MRL at 0.5 ppm is applicable until April 25, 2024."`, 삭제는 `delete`.
- bulk/API 없음 → 농약×식품 폼 조회 후 상세 파싱. (§30 selector fingerprint 필수)

### 2.4 Codex — p_id 상세페이지 (✅ 확인)
- `pesticide-detail/en/?p_id=N` — **Fludioxonil=211, Azoxystrobin=229**.
- 표: `Commodity | MRL | Year of Adoption | Symbol | Note`. Symbol `Po`(수확후처리), `(*)`(LOD 수준).
- **그룹 commodity**: 사과·배는 개별 없이 **`Pome fruits (group)`** 로 제공 → 그룹 매핑 필수.

## 3. 핵심 결과 — Fludioxonil × 4작물 (전 소스 실값)

RDA `외국`은 해당 행 `국가`의 캐시 MRL(=일본), `한국`은 국내 지침값. 단일성분 `플루디옥소닐(액상수화제)` 기준.

| 작물 | RDA 한국(국내) | RDA 외국(일본 캐시) | **Japan 라이브** | **Codex 라이브** | **EU 라이브** |
|---|---|---|---|---|---|
| 딸기(Strawberry) | 2 | 5 | **5** (Ab2011) | **3** (2006) | **4.00** (id39/0152000) |
| 포도(Grape) | 5 | 5 | **5** (Ab2011) | **2** (2006) | **5.00** (0151010) |
| 사과(Apple) | — (수출조합 없음) | — | **5** (Ad2011) | **5** (Pome fruits group) | **5.00** (0130010) |
| 배(Pear) | — (수출조합 없음) | — | **5** (Ad2011) | **5** (Pome fruits group) | **5.00** (0130020) |

### 3.1 Deterministic 판정 (코드로 계산, LLM 미사용 — §5)

**(A) RDA 캐시 최신성 검증** — 본 시스템의 최우선 목적(§36):
- 딸기: RDA 외국(일본 캐시)=5 **==** Japan 라이브=5 → **MATCH** (RDA 지침이 최신, `FOREIGN_CHANGED` 아님)
- 포도: RDA 외국=5 **==** Japan 라이브=5 → **MATCH**
- → "최신 데이터를 정상 확인했고, 그 결과 변경 없음"을 **증명**함 (Source: Japan, 상태 HEALTHY, 데이터 기준일 2026-08-07).

**(B) 국내(한국) vs 해외 규정 — 수출 적합성**:
| 작물 | vs Japan | vs EU | vs Codex |
|---|---|---|---|
| 딸기 (한국 2) | 2<5 → `RDA_STRICTER` | 2<4 → `RDA_STRICTER` | 2<3 → `RDA_STRICTER` |
| 포도 (한국 5) | 5=5 → `MATCH` | 5=5 → `MATCH` | **5>2 → `RDA_HIGHER`** ⚠️ |

- **포도/Codex의 `RDA_HIGHER`(한국 5 > Codex 2)** 는 Codex 기준 적용 시장으로의 수출에서 리스크 신호 → Severity 상향 대상.

## 4. 2차 확인 — Azoxystrobin (EU·Codex·RDA캐시)

| 작물 | RDA 한국 | RDA 외국(일본 캐시) | Codex 라이브 | EU 라이브 |
|---|---|---|---|---|
| 딸기 | (혼합제 내 존재) | — | **10** (2009) | **10.00** |
| 포도 | 3 (혼합제 아족시스트로빈.플루디옥소닐) | 10 | **2** (2009) | **3.00** |
| 사과 | — | — | (Pome) | **0.01\*** (기본값=미설정) |

- 딸기: Codex 10 **==** EU 10.00 → `MATCH`.
- 포도: 한국 3 **==** EU 3.00 → `MATCH`, 한국 3 **>** Codex 2 → `RDA_HIGHER`.
- 사과: EU `0.01*`(LOD) → EU에 특정 MRL 미설정. `NO_FOREIGN_STANDARD`/기본값으로 구분해 표기해야 함.
- **혼합제 분해 실증**: RDA `아족시스트로빈.플루디옥소닐(액상수화제)` 포도 → 외국 `10|5`, 한국 `3|5`
  → 성분1(azoxystrobin) 일본10/한국3, 성분2(fludioxonil) 일본5/한국5. **파이프-성분 위치대응 규칙이 실제로 성립**.

## 5. 검증으로 확인된 핵심 사실 (설계 반영 필수)

1. **비교는 deterministic하게 성립한다.** MRL은 모든 소스에서 숫자로 추출되어 직접 비교 가능(LLM 불필요).
2. **RDA 캐시 최신성 검증이 실제로 동작한다.** 일본 캐시=일본 라이브 확인으로 "이상 없음"을 *증명*으로 승격.
3. **commodity 매핑은 반드시 코드 기반.** 이름 매칭의 위험이 실증됨:
   EU `"Strawberry"`(id254, code **0632010** = 허브침출용) vs `"(b) strawberries"`(id39, code **0152000** = 과일).
   이름으로 잡으면 딸기(과일) 대신 엉뚱한 값(0.05\*)을 얻는다 → §11 `AMBIGUOUS`/`MANUAL_MAPPING` 필요.
4. **그룹 commodity 매핑 필요.** Codex는 사과·배를 `Pome fruits (group)=5`로만 제공.
5. **RDA는 수출 조합만 포함.** 일본×사과/배=0건. 비교대상 부재를 "불일치"로 오판하면 안 됨.
6. **특수 MRL 값 처리 규칙 필요**: `면제`(RDA Exemption), `0.05*`/`(*)`(EU/Codex LOD·기본값), `delete`(Japan 삭제), `Po`(수확후처리).
7. **시행일/기준일 확보 가능**: Japan Remarks·Setting Basis, Codex Year, EU(별도 필드), RDA(데이터셋 기준일 20251125).
8. **명칭 이질성 실증**: 같은 작물이 소스마다 `딸기`(RDA) / `Strawberry`,`(b) strawberries`(EU/Codex) / `Strawberry`(Japan);
   사과 `Apple (including peduncles)`(Japan) / `Apples`(EU) / `Pome fruits group`(Codex) → pesticide/commodity master 불가피.

## 6. 구현(STEP 5)로 넘길 확정 스펙 요약

| 소스 | 수집 방식 | 확정된 접근 | 신뢰도 |
|---|---|---|---|
| RDA | API | odcloud UDDI + `cond[::EQ]`/`cond[::LIKE]`, serviceKey | 높음 |
| EU | API | SANTE Datalake, `pesticide-residues-products`→PRODUCT_ID→`product-current-mrl-all-residues`, nextLink 페이징, 무키 | 높음 |
| Codex | 스크레이핑 | `pesticide-detail?p_id=N`(안정), 그룹 commodity 처리, fingerprint | 중간 |
| Japan | 폼 크롤링 | 검색→`showDetail(code,'mn')`→상세표, fingerprint | 낮음(취약) |

## 7. 남은 확인 항목 (STEP 5 착수 전)

1. EU `pesticide-residues-mrls`(3.5절) 의 substance/product 필터 파라미터 정밀 확정(문서 3.5 파라미터 표 추출) — product 단위(`product-current-mrl-all-residues`)로 이미 우회 가능.
2. EU 유효성분 등록상태(`active-substances`) 필드와 RDA 성분 매핑(§B 등록비교 확장).
3. Japan/Codex 파서 selector fingerprint 기준선 확정(§30).
4. pesticide_master/commodity_master 초기 사전 구축(딸기·사과·배·포도 + 검증대상 농약 우선).
5. Azoxystrobin 등 2차 농약의 Japan 라이브값 재확인(본 검증은 EU·Codex·RDA캐시까지 수행).

---
*본 문서는 STEP 4 산출물이다. 수치는 2026-08-18 실측이며, 규정은 상시 변동하므로 값 자체가 아니라 **수집·비교 방법의 성립**이 검증 대상이다.*
