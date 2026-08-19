# DATA_SOURCES.md — 공식 Data Source 조사 (STEP 1)

> 수출농산물 농약 안전사용기준 상시점검·변경탐지 서비스 PoC
> 작성일: 2026-08-18 · 상태: STEP 1 (조사·문서화 단계, 구현 이전)

## 0. 문서의 원칙

- 본 문서는 **실제로 확인한 사실만** 기록한다. 추측한 API/URL/데이터구조는 기준값으로 사용하지 않는다.
- 각 항목에는 검증상태를 표기한다.
  - ✅ **검증됨** — 2026-08-18 세션에서 실제 API 호출 또는 브라우저 조회로 직접 확인
  - ⚠️ **확인필요** — 공식 출처·경로는 특정했으나 정확한 endpoint/schema/키는 구현 전 재확인 필요
- **비공식 사이트·블로그·검색엔진 결과·2차 가공 데이터는 규정 기준값으로 사용하지 않는다.**
  본 문서의 모든 기준 소스는 규제기관/국제기구/정부 공식 데이터셋에 한정한다.

## 1. Source 계층 (§6)

| 계층 | Source | 역할 | authoritative 여부 |
|---|---|---|---|
| Domestic guideline | RDA 수출농산물 농약안전사용지침 | 국내 지침(비교 기준 좌변) | 국내 지침에 대해 authoritative |
| Current regulation | EU / Japan / (향후 US·Taiwan·China·Canada·Australia·HK) | 수입국 현행 규정 | 각국 MRL/등록에 대해 authoritative |
| International reference | Codex (FAO/WHO) | 국제 참조 MRL | 국제 참조값 |
| Early warning | WTO ePing / SPS | 변경 예고 탐지 전용 | ✗ (MRL 기준값으로 쓰지 않음, §16) |

## 2. 데이터 획득 우선순위 (§8) — 모든 Source 공통

1. 공식 API → 2. 공식 JSON/XML → 3. 공식 CSV/XLSX 다운로드 → 4. 공식 데이터셋 →
5. 정적 HTML → 6. 동적 웹페이지 crawling

API 또는 다운로드 파일이 있으면 HTML crawling보다 **반드시 우선** 사용한다.

---

## 3. Source별 상세

각 Source는 다음 템플릿으로 기술한다:
`공식 URL / 규제기관 / API여부 / 다운로드여부 / 데이터구조 / MRL / 등록상태 / PHI·사용조건 / update cycle / crawling필요 / 획득경로 / 검증상태 / 미확인 검증절차`

---

### 3.1 RDA — 수출농산물 농약안전사용지침 · ✅ 검증됨 (실 호출 완료)

| 항목 | 내용 |
|---|---|
| 규제기관 | 농촌진흥청 (RDA), odcloud 공공데이터포털 제공 |
| 공식 Base URL | `https://api.odcloud.kr/api` |
| 데이터셋(UDDI) | `15154138/v1/uddi:eacf7771-ca89-4612-bbe2-c430042a3073` |
| Swagger | `https://infuser.odcloud.kr/oas/docs?namespace=15154138/v1` |
| 데이터셋명 | `농촌진흥청_수출농산물 농약안전사용지침_20251125` |
| API 여부 | ✅ 있음 (REST, JSON/XML) |
| 인증 | `serviceKey`(query) 또는 `Authorization` 헤더. 파라미터: `page`, `perPage`, `returnType` |
| 조건필터 | ✅ `cond[<컬럼>::EQ]`, `cond[<컬럼>::LIKE]` 작동 확인(STEP4). `matchCount`로 필터건수 확인 |
| 수록 범위 | ✅ **수출 (국가×작목) 조합만 수록** (예: 일본×사과/배 = 0건). 비교대상 부재를 불일치로 오판 금지 |
| 다운로드 | API 페이지네이션으로 전량 수집 가능 (perPage 조정) |
| **총 레코드** | **35,975건 (2026-08-18 실측)** |
| 저장 순서 | 국가별로 그룹/정렬되어 있음 (page 1 = EU, page 200 = 중국 관측) |
| MRL 제공 | ✅ `외국`(수입국 MRL) / `한국`(국내 지침 MRL) 두 컬럼 |
| 등록상태 제공 | ✗ 컬럼 없음 |
| PHI·사용조건 | 부분: `횟수`, `약량` 있음 / **PHI·희석배수·시행일 없음** |
| update cycle | 지침 개정 시 (데이터셋명에 기준일 `20251125` 포함). 신규 개정본은 별도 UDDI로 게시될 수 있음 → **UDDI 변경 감시 필요** |
| crawling 필요 | ✗ (공식 API 사용) |

**실제 컬럼 (11개):**
`국가, 작목, 용도, 적용병해충, 품목명, 작용기작, 상표명, 횟수, 약량, 외국, 한국`

**실측 레코드 예시:**
```json
{
  "국가": "EU", "작목": "배", "용도": "살충제",
  "적용병해충": "가루깍지벌레",
  "품목명": "델타메트린.스피로테트라맷(액상수화제)",
  "작용기작": "3a,23", "상표명": "락다운",
  "횟수": "3", "약량": "10mL",
  "외국": "0.09|0.7|-", "한국": "0.5|0.5|-"
}
```

**⚠️ 중요 구조 규칙 (반드시 파서에 반영):**
- `외국`·`한국` 값은 파이프(`|`)로 분할된 배열이다.
- 배열의 각 세그먼트는 `품목명`의 점(`.`)으로 구분된 **혼합제 유효성분과 위치 대응**한다.
  - 예: `품목명 = "디클로벤티아족스.티플루자마이드.클로티아니딘(입제)"` (성분 3개)
    → `한국 = "0.05|0.3|0.1"`, `외국 = "-|3|0.2"` → 성분별 MRL.
  - `-` = 해당 성분에 대한 MRL 미설정.
  - 단일성분 제품은 첫 칸만 채워지고 나머지는 `-`.
- 따라서 MRL 비교 전에 **품목명 → 유효성분 분해 → 세그먼트 정렬** 단계가 선행되어야 한다. (§FIELD_MAPPING)

**핵심 한계 (비교 설계에 직접 영향):**
- CAS 번호 ✗ / 영문 품목명·유효성분 ✗ / 작물 학명 ✗ → pesticide_master·commodity_master 매핑 필수 (§10·§11).
- **PHI ✗ / 희석배수 ✗ / 규정 시행일(effective date) ✗ / 등록상태 ✗**.
- `약량`은 `"740mL,(0.8L/10a)"`, `"50g/상자"` 처럼 dose+면적환산+포장단위가 섞인 자유텍스트 → 정규화 필요.

**시사점:** 이 데이터셋은 RDA가 **이미 캐시해 둔 `외국`(수입국) MRL**을 포함한다. 본 시스템의 핵심 임무는
그 `외국` 값을 **라이브 해외 공식 소스로 독립 재검증**하여, RDA 캐시값과 해외 현행값의 stale/불일치를 탐지하는 것이다.

---

### 3.2 EU · ✅ 검증됨 (API·다운로드 존재 확인) / ⚠️ 필드 스키마는 구현 시 확정

| 항목 | 내용 |
|---|---|
| 규제기관 | European Commission, DG SANTE (Directorate-General for Health and Food Safety) |
| 공식 UI | `https://food.ec.europa.eu/plants/pesticides/eu-pesticides-database_en` (EU Pesticides DB v3.4, Angular SPA) |
| **권장 획득경로** | **EU Open Data Portal 데이터셋 "EU Pesticides"** |
| └ 데이터셋 URI | `http://data.europa.eu/88u/dataset/pesticides` (id: `planthealth-pesticides`) |
| API 여부 | ✅ 있음 (공식 JSON API 다수) |
| 다운로드 | ✅ 있음 (JSON / CSV / XML) |
| update cycle | ✅ **`Accrual Periodicity: daily`** (포털 메타데이터 실측), 최종갱신 2026-04 |
| MRL 제공 | ✅ (pesticide/commodity MRL 조합) |
| 등록상태 제공 | ✅ (Active Substances 승인 상태) |
| PHI·사용조건 | △ (MRL DB에는 미포함. 제품승인은 회원국별 소관) |
| crawling 필요 | ✗ 권장 안 함 — SPA는 JS 렌더로 취약. **API/다운로드 사용** |

**✅ 실제 API 확정 (STEP 4에서 직접 호출·검증, 인증키 불필요):**
- Base: `https://api.datalake.sante.service.ec.europa.eu/sante/pesticides/`
- 엔드포인트/파라미터 (EU 공식 `Pesticides-APIs-V3.0.pdf`에서 추출):
  | 엔드포인트 | 파라미터 | 용도 |
  |---|---|---|
  | `pesticide-residues-products` | `language`(필수)`,format,product_id,product_parent_id,product_code,product_type_id,api-version=v3.0` | 작물목록(381개) |
  | `product-current-mrl-all-residues` | `PRODUCT_ID`(필수)`,format,api-version=v3.0` | 한 작물의 전체 현행 MRL |
  | `active-substances` | `substance_id,substance_name,substance_status,approval_date,expiry_date,substance_category` | 등록/승인 상태 |
  | `pesticide-residues-mrls-download` | `language`(필수)`,format` | 전량 flat file(>10MB) |
- 페이징: `{value:[...], nextLink:"...&$after=<cursor>"}`, page size 100.
- MRL 필드: `PRODUCT_ID, PEST_RES_ID, MRL_VALUE, MRL_LOD, MRL_DISPLAY, PESTICIDE_RESIDUE_NAME, MRL_FOOTNOTE`.
  `MRL_LOD="*"`+`MRL_DISPLAY="0.05*"` = 기본값/LOQ(미설정).
- 작물코드 = EU Reg 396/2005 Annex I (0130010 Apples, 0130020 Pears, 0151010 Table grapes, 0152000 strawberries).
- ⚠️ 주의: 작물명 중복(`Strawberry` 0632010=허브침출 vs `(b) strawberries` 0152000=과일) → **코드로 매핑**. 간헐적 HTTP 500(재시도).
- 상세 실측·비교결과는 [FIELD_MAPPING.md](FIELD_MAPPING.md)·[STEP4_VALIDATION.md](STEP4_VALIDATION.md) 참조.

---

### 3.3 Japan · ✅ 구현·수집 중 (FFCR DB, 폼 세션 + HTML 표)

| 항목 | 내용 |
|---|---|
| 규제기관 | 소비자청(CAA) / 후생노동성(MHLW) — Positive List 제도 |
| **실제 수집원** | `https://db.ffcr.or.jp/front/` — 공익재단법인 일본식품화학연구진흥재단(FFCR) 잔류농약기준 검색시스템 (영문판) |
| 원문 DB | `https://jpn-pesticides-database.go.jp/prdb/` — **해외 IP/봇을 403 차단**(실측). 자동 수집 불가 |
| API 여부 | ✗ (폼 기반) |
| 접근 절차 | ① `GET /front/?lng=en` (세션에 영문 표기) → ② `POST /front/?m=p` (성분 첫 글자) → ③ `GET /front/pesticide_detail?id=N`. ②를 건너뛰고 ③만 호출하면 첫 화면으로 리다이렉트된다(세션 상태 필요) |
| 상세표 컬럼 | `Food Type` / `MRLs(ppm)` / `Basis of setting` / `Note` / `MRLs(ppm)(Time limit for application)` |
| MRL 제공 | ✅ 본 기준 + **경과조치 기한부 기준**(기한 포함) |
| 시행일 제공 | △ `Basis of setting` 코드(예: `Ab2025`)로 **설정 고시 연도**를 알 수 있다. 원문 DB의 施行日(備考)만큼 정밀하지는 않다 |
| 일률기준 | 표에 해당 작목 행이 없으면 포지티브리스트 **일률기준 0.01 ppm** 적용 (`is_default=True`로 개별기준과 구분) |
| 식품명 어휘 | 상세표의 `Food Type` 표기 154종을 실측 수집해 `masters.COMMODITIES.japan_name`과 대조. 목록에 없는 이름은 매핑하지 않는다(§30) |
| authoritative | **CAA 官報(관보)** — FFCR도 "정확한 정보는 官報으로 재확인" 명시 |

**⚠️ 이용 조건:** FFCR 자료는 고시 원문이 아니라 재단 편집본이며 **무단 전재·복제를 금지**한다.
수집값은 모니터링·내부 검토용으로만 쓰고, 지침 개정 근거로 쓸 때는 관보/후생노동성 고시 원문으로 재확인한다.

**개선 여지:** 국내망에서 `jpn-pesticides-database.go.jp` 접근이 된다면 원문 DB가 施行日을 직접 제공하므로
`JAPAN_OFFICIAL`(config.py)을 1순위로 쓰고 FFCR을 fallback으로 두는 편이 낫다. 현재는 접근 불가로 미구현.

---

### 3.5 USA · ✅ 구현·수집 중 (eCFR 공개 API, 규정 원문)

| 항목 | 내용 |
|---|---|
| 규제기관 | EPA (미국 환경보호청) |
| 수집원 | `https://www.ecfr.gov/api/versioner/v1/full/{date}/title-40.xml?part=180` — **40 CFR Part 180 전문 XML** (무키) |
| 근거 규정 | 40 CFR Part 180: Tolerances and Exemptions for Pesticide Chemical Residues in Food |
| 개정일 | `/api/versioner/v1/titles.json` 의 title 40 `latest_issue_date` 를 data_date 로 기록 |
| MRL 제공 | ✅ 성분별 절(§180.xxx)의 허용량 표 (Commodity / Parts per million) |
| authoritative | ✅ 규정 원문 자체 |

**작물그룹(Crop Group) 해석 — 이 소스의 핵심 난점**

EPA는 개별 작물이 아니라 **작물그룹** 단위로 허용량을 정하는 경우가 많다.
예: 사과 기준은 `Apple` 행이 아니라 `Fruit, pome, group 11-10` 행에 있다.
그룹 구성 작물은 **§180.41 에 규정 자체로 정의**돼 있어 추측 없이 색인할 수 있다.
§180.41 은 두 가지 형태를 섞어 쓴다 — `<EXTRACT>` 목록(그룹 11-10 등)과 `<TABLE>`(그룹 1, 13-07 등). 둘 다 파싱한다.

채택 규칙(`collectors/usa.py:resolve`):
1. 표의 commodity 가 대상 작물명과 **정확히** 일치하면 채택(개별 기준이 그룹보다 우선).
2. 아니면 `group NN` / `subgroup(s) NN-NNX` 를 가리키는 행 중, 그 그룹에 대상 작물이 속하고
   `except ...` 로 제외되지 않은 행을 채택.
3. 후보가 여러 개인데 **값이 서로 다르면 채택하지 않는다**(담당자 확인 대상).

**주의해서 처리한 함정 (모두 회귀 테스트로 고정)**
- `Apple, wet pomace`(사과박)는 **신선 사과가 아니다.** commodity 표기를 쉼표에서 자르면
  가공품 기준(예: 디페노코나졸 25 ppm)을 신선 과실(5 ppm)에 붙이게 된다 → 쉼표를 자르지 않는다.
- 한국 배는 **아시아배**(Pyrus pyrifolia). CFR 은 `Pear, Asian` 을 따로 등재하며 값이 다르다
  (아족시스트로빈: pome 그룹 없음 vs Pear, Asian 0.07). `usa_name = "Pear, Asian"`.
- §180.41 구성작물은 `이름, <I>학명</I> 저자` 형식이므로 **첫 `<I>` 앞까지**가 작물명이다.
  쉼표로 자르면 `pear, asian` 이 `pear` 로 뭉개진다.
- 허용량 표의 각주 표식은 `<sup>` 이다(`Pear, Asian <sup>1</sup>`) → 제거 후 비교.
- 그룹 참조는 `subgroup` 과 `subgroups`(복수)가 섞여 쓰인다.
- 성분명이 다를 수 있다: 아바멕틴은 `Avermectin B1 and its delta-8,9-isomer`(§180.449)로 등재
  → `PESTICIDES[...]["usa_name"]` 로 지정.

---

### 3.6 Taiwan · ✅ 구현·수집 중 (TFDA 정부 오픈데이터)

| 항목 | 내용 |
|---|---|
| 규제기관 | 위생복리부 식품약물관리서(TFDA) |
| 수집원 | `https://data.fda.gov.tw/data/opendata/export/13/json` — 農藥殘留容許量標準 (무키) |
| 작물분류표 | `.../export/16/json` — 農作物類農產品之分類表 (그룹 해석용) |
| 엔드포인트 근거 | TFDA 가 게시한 OpenAPI 명세에서 확인(추측 아님): swagger-config → 食品 분류 → `paths` |
| **필수 헤더** | `Accept: application/json` — **없으면 HTML 페이지가 돌아온다**(실측) |
| 레코드 | `國際普通名稱`(영문 일반명) / `普通名稱` / `作物類別` / `容許量ppm` / `備註` |
| 규모 | MRL 8,258건 · 작물분류 22류 |
| authoritative | 대만 官方 공고 기준 |

**作物類別 해석**
1. 개별 작물 — `蘋果`, `桃(油桃除外)` → 정확히 일치하면 채택(그룹보다 우선)
2. 류 전체 — `梨果類`
3. 류에서 일부 제외 — `其他小漿果類(藍莓、覆盆子除外)`

**주의해서 처리한 함정 (회귀 테스트로 고정)**
- 제외구가 **작물명이 아니라 소분류명**으로 오는 경우가 있다:
  `其他包葉菜類(十字花科包葉菜類、結球萵苣除外)`. 분류표 본문의 `十字花科包葉菜【甘藍…、結球白菜…】`
  처럼 `【】` 로 묶인 소분류를 따로 색인하지 않으면 **배추·양배추에 남의 기준을 붙이게 된다**
  (실측: 아바멕틴 0.05→0.02 가짜 CRITICAL 2건 발생).
- 괄호 안 `、` 때문에 목록 분리가 깨진다 → 괄호 내용을 먼저 제거하고 분리.
  단 괄호 안 하위 작물(`木莓(包括覆盆子、黑莓等)`)은 그 류의 구성원이므로 별도로 수집.
- 분류표는 `柿子`, 허용량표는 `柿` — 표기 차이는 `CLASS_ALIAS` 로 **명시적으로만** 잇는다.
- 제외 토큰의 정체를 모르면(구성원도 소분류도 아님) 그 행은 쓰지 않는다 — 보수적 판단.

---

### 3.8 Indonesia · ⏸ 보류 (수집 불가)

| 항목 | 내용 |
|---|---|
| 기준 | **SNI 7313:2024** — 272 성분 × 406 품목, 약 4,750 MRL 값 (SNI 7313:2008 개정) |
| 발행 | BSN(국가표준화청) / 농업부 |
| 자동 수집 | ❌ **불가** |
| 현재 상태 | **보류** (`SOURCES['Indonesia']['deferred']`) — 매 실행마다 실패 알림을 내지 않는다 |
| 재개 조건 | 담당 연구사가 실제 참고하는 사이트 확인. 끝내 없으면 수동 입력 CSV(`data/manual/`)로 대체 |

**접근 차단 실측 (2026-08-20, 이 서버 및 외부 fetch 양쪽)**

| 호스트 | 결과 |
|---|---|
| `bsn.go.id` (표준 원문 PDF 게시처) | 연결 타임아웃 / ECONNREFUSED |
| `brmp.pertanian.go.id` (농업부 공개자료) | Cloudflare 403 |
| `repository.pertanian.go.id` | 403 |
| `data.go.id` (국가 오픈데이터) | 200 이지만 잔류농약 기준 데이터셋 없음 |
| `kemendag.go.id` (대조군, 다른 인니 정부기관) | 200 |

대조군이 열리므로 국가 단위 차단이 아니라 **해당 호스트들이 해외 트래픽을 막는 것**으로 보인다.
국내망에서 접근이 된다면 자동 수집으로 전환할 수 있다.

**수동 입력을 택한 근거**: SNI 7313 은 2008 → 2024, 16년 만의 개정이다. 매일 긁을 대상이 아니며
담당자가 표준을 한 번 확보해 넣으면 다음 개정까지 유효하다. 입력값에는 `standard`(예: SNI 7313:2024)와
`effective_date` 를 함께 받아 근거·기준일이 화면에 남는다. 파일이 없는 동안에는 `SOURCE_UNAVAILABLE`
로 두어 "확인하지 못함"을 "이상 없음"으로 오해하지 않게 한다(§22).

---

### 3.7 Hong Kong · ✅ 구현·수집 중 (CFS 조회 시스템)

| 항목 | 내용 |
|---|---|
| 규제기관 | 식품안전센터(CFS) / 식품환경위생서(FEHD) |
| 근거 규정 | **Pesticide Residues in Food Regulation (Cap. 132CM) Schedule 1** |
| 수집원 | `https://www.cfs.gov.hk/english/mrl/` — Pesticide MRL Database |
| API 여부 | ✗ (이용약관 동의 → 성분 선택 → 식품 선택 → 조회, 세션 기반 폼) |
| 규모 | 성분 360종 · 식품 422종 |
| 식품 식별자 | ✅ **Codex 품목코드** (예: Pear = `FP 0230`, Peach = `FS 0247`) — 표기가 안정적 |
| 응답 | 항목번호 / 조항 / 성분 / 잔류물정의 / 식품설명 / MRL(mg/kg) |

**접근 절차 (실측 확정)**
1. `POST mrl_preinput.php` (`acceptTC=true`) — 세션 확보
2. `POST mrl_select_pesticide.php` (`ShowallAction=Y`) — 성분 목록 + `pest_id`
3. `POST mrl_select_food.php` (`ShowallAction=Y`) — 식품 목록 + `food_id`(Codex 코드)
4. `POST mrl_report.php` (`pest_id`, `food_id`) — 해당 조합의 MRL 행

**주의점**
- 버튼 필드명이 `Showall` 이 아니라 **`ShowallAction`** 이다. 틀리면 결과 없이 폼이 다시 돌아온다.
- `Peach`(FS 0247)와 `Peach, dried`(DF 0247)는 다른 품목이다 — 정확 일치로만 고른다.
- Codex 코드는 사이트 목록에서 매 수집마다 해석한다(코드베이스에 박지 않음).
- 조합에 기준이 없으면 값을 만들지 않는다. 홍콩은 미등재 시 일률기준이 따로 없어
  임의 기본값을 넣으면 틀린 판정이 된다.
- (성분×작물) 조합마다 1회 요청이라 대상 규모에 비례해 요청이 늘어난다(현재 72회, 0.3초 간격).

---

### 3.9 Canada · ✅ 구현·수집 중 (PMRA 공개 추출 CSV)

| 항목 | 내용 |
|---|---|
| 규제기관 | Health Canada / 해충관리규제국(PMRA) |
| 수집원 | `https://pest-control.canada.ca/pesticide-registry-api/api/extract/mrl` (무키) |
| 형식 | CSV · **WINDOWS-1252** · 25,469행 |
| 컬럼 | Chemical Common Name / Food Commodity / MRL Value (ppm) / Comments / **Established Via** |
| 근거·시점 | `Established Via` 에 근거 문서와 날짜가 그대로 들어 있다 (예: `MRL Database (26 April 2026) consulted via PMRL2026-02`) |

**주의점**
- 캐나다도 미국식 작물그룹(`CROP GROUP 10`, `CROP SUBGROUP 13-07H`) 표기를 쓰지만
  **그룹 구성 정의가 이 파일에 없다.** 근거 없이 펼치면 다른 작물의 기준을 붙이게 되므로
  개별 품목 등재만 채택한다. 대상 작목 기준 12성분 중 10~11건이 개별 등재라 실익이 적다.
- 한국 배는 아시아배 — `Asian pears` 와 `Pears` 가 따로 등재되고 값이 다르다.
  `canada_name = ["Asian pears", "Pears"]` 순으로 조회한다.

---

### 3.10 미연결 국가 — 조사 기록 (2026-08-20)

다음 라운드에서 같은 조사를 반복하지 않도록 실측 결과를 남긴다.

| 국가 | 지침 행수 | 소스 | 상태 |
|---|---|---|---|
| 중국 | 1,303 | GB 2763 (CFSA) | `cfsa.net.cn` TLS 체인 오류, `sppt.cfsa.net.cn:8086/db` 응답 625B(JS). GB 표준은 유료 가능성 — 미해결 |
| 호주 | 441 | FSANZ Schedule 20 (F2015L00468, 현행 컴필레이션 **F2026C00754**, 2026-07-16) | legislation.gov.au 는 **SPA** 라 `/latest/text`·`/Details/.../Download` 모두 63KB 셸만 반환. OData API(`api.prod.legislation.gov.au/v1`)로 Versions·Documents 메타(docx 713KB / pdf 1.5MB)는 조회되나 **파일 다운로드 URL 을 못 찾음** — 미해결 |
| 태국 | 370 | ACFS | 사이트 접근 200. MRL 데이터셋 위치 미확인 |
| 뉴질랜드 | 350 | MPI Food Notice (MRLs for Agricultural Compounds) | 접근 200. 호주 Schedule 20 과 **별개 기준**이다(상호인정은 되지만 기준 자체가 다름) |
| 러시아 | 335 | EAEU / SanPiN | `eaeunion.org` 접근 200. 기준 문서 위치 미확인 |
| 싱가폴 | 314 | SFA Food Regulations | `data.gov.sg` 접근 200. MRL 데이터셋 미확인 |

**확인된 패턴**: 공개 API 가 있는 나라(미국 eCFR, 대만 TFDA, 캐나다 PMRA)는 하루면 붙고,
표준이 유료이거나(인니 SNI, 중국 GB) 문서가 SPA 뒤에 있으면(호주) 막힌다.
담당 연구사가 실제로 참고하는 사이트를 확인하면 크게 단축될 수 있다.

---

### 3.4 Codex (FAO/WHO) · ✅ 검증됨 (구조 확인, bulk/API 미노출)

| 항목 | 내용 |
|---|---|
| 규제기관 | FAO/WHO Codex Alimentarius Commission (국제 참조) |
| 공식 DB | `https://www.fao.org/fao-who-codexalimentarius/codex-texts/dbs/pestres/pesticides/en/` |
| 상세 URL 패턴 | `.../dbs/pestres/pesticide-detail/en/?p_id=N` (N = 안정적 정수 ID) |
| API 여부 | ⚠️ 미노출 |
| 다운로드 | ⚠️ bulk CSV/XLSX 미노출 |
| 데이터구조 | 농약 인덱스(알파벳/ID) → 농약별 상세에 commodity별 MRL 표 |
| MRL 제공 | ✅ (국제 참조 MRL) |
| 등록상태·PHI | ✗ (Codex는 등록/PHI 아님, MRL 중심) |
| update cycle | JMPR 평가 → CCPR/CAC 채택 (연 주기, ⚠️ 정확 주기 확인필요) |
| crawling 필요 | ✅ **필요** — 농약별 상세페이지 스크레이핑 (p_id 순회) |

**실측된 안정 식별자 예시:** `Fludioxonil=211`, `Deltamethrin=135`, `Chlorantraniliprole=230`, `Imidacloprid=206`, `2,4-D=20`.
→ p_id는 안정적이므로 **pesticide_master의 `Codex_identifier`로 활용** 가능 (§10).

**⚠️ 검증절차 (구현 전):**
1. 상세페이지(`?p_id=N`)의 HTML 표 구조·컬럼(commodity, MRL, step/year 등)을 확정하고 selector fingerprint 저장(§30).
2. p_id 전체 범위(인덱스에서 수집)를 순회하는 방식으로 전량 확보.
3. bulk 파일/API 존재 여부를 Codex 사무국 문의로 재확인(있다면 우선순위 상향).

---

### 3.5 WTO ePing / SPS · ✅ 검증됨 (API·키·엔드포인트·응답필드 전부 확인)

| 항목 | 내용 |
|---|---|
| 용도 | **authoritative MRL 아님. 향후 변경 탐지(Early warning) 전용** (§16) |
| API 포털 | `https://apiportal.wto.org` (계정 가입 → Products → Standard 구독) |
| **API Base URL** | ✅ **`https://api.wto.org/eping/`** (Azure API Management) |
| 제품/등급 | `Standard` (묶음: ePing + Quantitative Restrictions + Timeseries), **무료**. 10 calls/s, 10,000/hour |
| 인증 | ✅ 헤더 `Ocp-Apim-Subscription-Key: <키>` 또는 쿼리 `?subscription-key=<키>`. 키는 `.env`의 `WTO_API_KEY` |
| 검증 결과 | ✅ 2026-08-18: members 164개 반환, **notifications/search `totalCount 104,818` 정상 반환** |

**엔드포인트 (검증됨):**
- `GET /eping/members?language={1\|2\|3}` — 회원국 목록 (코드 예: Viet Nam=`C704`)
- `GET /eping/notifications/search?language=1&...` — **SPS/TBT 통보문 검색 (핵심)**
  - 파라미터: `language`(필수, 1=EN), `domainIds`(SPS/TBT), `documentSymbol`,
    `distributionDateFrom`, `distributionDateTo`, `countryIds`, `hs`, `ics`, `freeText`, `page`, `pageSize`
  - 응답 top-level: `currentPage`, `pageSize`, `totalCount`

**통보문 레코드 핵심 필드 (검증됨) → 본 시스템 매핑:**
| ePing 필드 | 용도 |
|---|---|
| `area` (SPS/TBT) | SPS만 필터 |
| `notificationType` | Regular/Emergency 등 구분 |
| `distributionDate` | 통보 배포일 → 변경탐지 기준일 |
| `commentDeadlineDate` | 의견마감일 → `COMMENT_PERIOD` 상태(§16) |
| `proposedAdoptionDate(Text)` | 채택예정 → `ADOPTED` 예고 |
| `proposedEntryIntoForceDate(Text)` | **시행예정일** → `EFFECTIVE`/`UPCOMING_CHANGE`(§4·§16) |
| `notifyingMember(Code)` | 통보국 (수입국 매칭) |
| `title/description(Plain)`, `productsFreeText(Plain)` | LLM 요약·분석 대상(§5, `AI_ANALYZED`) |
| `hsCodes/icsCodes/keywords/spsKeywords/objectives` | 농약·MRL 관련 통보 필터 (예: freeText="maximum residue") |
| `documentSymbol` (예: `G/SPS/N/VNM/190`) | 통보 식별자 |
| `notifiedDocumentLink`, `linkToNotification` | 원본 문서 링크(§9 보존) |
| `codexAlimentariusCommision` | Codex 관련 여부 플래그 |

**수집 전략:**
1. 일 단위 폴링: `area=SPS` + `distributionDateFrom=어제` 로 신규 통보 증분 수집.
2. 농약/MRL 관련만 선별: `freeText`(예: "maximum residue level", "pesticide") + `objectives`/`spsKeywords` 필터.
3. 수집값은 **변경 예고**로만 저장하고, **MRL 기준값으로 확정하지 않는다**(§16). 상태: PROPOSED~WITHDRAWN.
4. (대안) WTO Data Portal `data.wto.org` 데이터셋 `ext_eping` XLSX bulk 다운로드 병행 가능.

---

## 4. Source별 요약 매트릭스

| Source | 계층 | API | 다운로드 | crawling | MRL | 등록 | PHI/사용 | update | 검증상태 |
|---|---|---|---|---|---|---|---|---|---|
| RDA | Domestic | ✅ | ✅(API) | ✗ | ✅ | ✗ | 부분(횟수/약량) | 개정시 | ✅ 실호출 |
| EU | Current | ✅ | ✅ | 회피 | ✅ | ✅ | △ | **일 단위** | ✅ 존재확인 |
| Japan | Current | ⚠️미노출 | ⚠️미노출 | ✅필요 | ✅ | ✗(별도) | ✗(별도) | 부정기(월) | ✅ 구조확인 |
| Codex | Reference | ⚠️미노출 | ⚠️미노출 | ✅필요 | ✅ | ✗ | ✗ | 연 | ✅ 구조확인 |
| WTO ePing | Early warn | ✅ | ✅(XLSX) | ✗ | ✗(예고만) | — | — | 상시 | ✅ 전체검증(search) |

## 5. Collector 설계 시사점 (STEP 5 이후)

- Collector는 source별 독립 모듈(§7): `rda.py`(API), `eu.py`(API/다운로드), `japan.py`(폼 crawling),
  `codex.py`(p_id 스크레이핑), `wto_eping.py`(API/XLSX).
- 안정성 등급: **RDA·EU(높음, 구조화 API)** > **WTO(중간)** > **Japan·Codex(낮음, 스크레이핑 → §30 fingerprint 필수)**.
- 모든 수집은 원본 보존(§9): `source, URL, retrieved_at, HTTP_status, content_type, content_hash, file_hash, source_version, effective_date, raw_file_path`.

## 6. 미확인 항목 총괄 (다음 검증 대상)

| # | Source | 미확인 항목 | 검증 방법 |
|---|---|---|---|
| 1 | EU | 각 distribution의 정확 endpoint·필드·rate-limit | 포털 Access 링크 호출 |
| 2 | Japan | 검색 폼 내부 요청·응답 포맷, bulk/API 존재 | network 관측 + 도움말 PDF 텍스트 추출 |
| 3 | Codex | 상세페이지 표 컬럼·p_id 전체범위, bulk 존재 | 상세페이지 파싱 + 사무국 문의 |
| 4 | WTO | ✅완료 (base·키·members·notifications/search·응답필드 모두 검증) | — |
| 5 | RDA | 신규 개정본 게시 시 UDDI 변경 여부 | odcloud 목록 API 주기 점검 |
| 6 | (향후) | Japan 등록/PHI (JMAFF/ACIS), US/Taiwan/China 등 추가국 | 별도 STEP |

---
*본 문서는 STEP 1 산출물이다. 여기서 ⚠️로 남은 항목은 구현(STEP 5) 전에 반드시 실제 확인하며, 확인 전까지 코드에 확정값으로 넣지 않는다.*
