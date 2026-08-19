"""전역 설정: 경로, 소스 정의, 인증키, HTTP 옵션.

인증키는 .env에서 읽는다(커밋 금지). 값이 없으면 해당 소스는 비활성/스킵된다.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# ---- 저장 경로 ----
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"          # 원본 스냅샷 (§9)
OUT_DIR = BASE_DIR / "out"          # 생성된 보고서/대시보드
DB_PATH = DATA_DIR / "pesticide.sqlite"
MANUAL_DIR = DATA_DIR / "manual"    # 자동 수집이 불가능한 소스의 담당자 입력 파일
for _d in (DATA_DIR, RAW_DIR, OUT_DIR, MANUAL_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---- HTTP ----
# 로컬 테스트가 MITM 프록시를 지나면 검증 실패하므로 PESTICIDE_INSECURE=1 로 끌 수 있다.
# 운영(사용자 PC)에서는 반드시 검증 유지(기본 True).
HTTP_VERIFY = os.getenv("PESTICIDE_INSECURE", "0") not in ("1", "true", "True")
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "40"))
USER_AGENT = "pesticide-monitor/0.1 (+PoC)"

# ---- 인증키 ----
RDA_SERVICE_KEY = os.getenv("RDA_SERVICE_KEY", "")
WTO_API_KEY = os.getenv("WTO_API_KEY", "")

# ---- 소스 엔드포인트 (STEP1~4에서 실측 확정) ----
RDA_BASE = "https://api.odcloud.kr/api/15154138/v1/uddi:eacf7771-ca89-4612-bbe2-c430042a3073"
EU_BASE = "https://api.datalake.sante.service.ec.europa.eu/sante/pesticides"
EU_API_VERSION = "v3.0"
CODEX_DETAIL = "https://www.fao.org/fao-who-codexalimentarius/codex-texts/dbs/pestres/pesticide-detail/en/"
# 일본 현행 MRL: 후생노동성 원문 DB(jpn-pesticides-database.go.jp)는 해외 IP/봇을 403 차단하므로
# 고시(告示 370호)를 편집·공개하는 FFCR DB를 수집원으로 쓴다(collectors/japan.py 주석 참조).
JAPAN_BASE = "https://db.ffcr.or.jp/front/"
JAPAN_OFFICIAL = "https://jpn-pesticides-database.go.jp/prdb/"   # 원문(국내망에서 접근 시 우선)
WTO_BASE = "https://api.wto.org/eping"

# 미국 현행 MRL = 40 CFR Part 180. eCFR 이 규정 전문을 XML로 공개(무키).
USA_CFR_DATE_URL = "https://www.ecfr.gov/api/versioner/v1/titles.json"
USA_CFR_PART_URL = "https://www.ecfr.gov/api/versioner/v1/full/{date}/title-40.xml?part=180"
USA_SECTION_URL = "https://www.ecfr.gov/current/title-40/section-{section}"

# 대만 현행 MRL = TFDA 農藥殘留容許量標準 오픈데이터(무키).
# 엔드포인트는 TFDA OpenAPI 명세에서 확인(추측 아님). Accept: application/json 필수.
TAIWAN_MRL_URL = "https://data.fda.gov.tw/data/opendata/export/13/json"
TAIWAN_CLASS_URL = "https://data.fda.gov.tw/data/opendata/export/16/json"   # 農作物類農產品之分類表
TAIWAN_SOURCE_PAGE = "https://data.gov.tw/dataset/8944"

# 개정 감시 전용 소스 — 값은 기계 판독 불가, '현행판이 언제 바뀌었는지'만 추적한다.
CN_SEARCH_URL = "https://sppt.cfsa.net.cn:8086/db?task=indexSearch"
CN_SOURCE_PAGE = "https://sppt.cfsa.net.cn:8086/db"
AU_VERSIONS_URL = "https://api.prod.legislation.gov.au/v1/Versions"
AU_SCHEDULE20_TITLE = "F2015L00468"      # ANZ Food Standards Code – Schedule 20 – MRLs
SG_REG30_URL = "https://sso.agc.gov.sg/SL/SFA1973-RG1?ProvIds=pr30-"   # Food Regulations 30조

# 캐나다 현행 MRL = Health Canada/PMRA 공개 추출 CSV(무키).
CANADA_MRL_URL = "https://pest-control.canada.ca/pesticide-registry-api/api/extract/mrl"
CANADA_SOURCE_PAGE = "https://pest-control.canada.ca/pesticide-registry/en/mrl-search.html"

# 홍콩 현행 MRL = Pesticide Residues in Food Regulation (Cap. 132CM) Schedule 1.
# bulk/API 없음 — CFS 조회 시스템의 폼 세션을 그대로 따른다.
HK_BASE = "https://www.cfs.gov.hk/english/mrl/"
HK_SOURCE_PAGE = "https://www.cfs.gov.hk/english/mrl/index.php"

# 인도네시아 SNI 7313 — 표준 게시처가 해외 접근을 차단해 자동 수집 불가. 수동 입력 파일로 받는다.
INDONESIA_FILE = DATA_DIR / "manual" / "indonesia_mrl.csv"
INDONESIA_STANDARD_URL = "https://www.bsn.go.id/uploads/attachment/rsni3_7313_2024_siap_jp_ver_ok.pdf"

# ---- 소스 메타 (System Health / Freshness 기준, §18·§21) ----
# expected_update_interval 단위: 일(day). 초기값이며 실주기 확인 후 조정(문서 MONITORING §5).
SOURCES = {
    "RDA":   {"country": "KR",  "kind": "guideline", "interval_days": 30,  "authoritative": True},
    "EU":    {"country": "EU",  "kind": "regulation", "interval_days": 2,   "authoritative": True},
    "Japan": {"country": "JP",  "kind": "regulation", "interval_days": 45,  "authoritative": True},
    "Codex": {"country": "INT", "kind": "reference",  "interval_days": 400, "authoritative": False},
    "USA":   {"country": "US",  "kind": "regulation", "interval_days": 7,   "authoritative": True},
    "Taiwan": {"country": "TW", "kind": "regulation", "interval_days": 30,  "authoritative": True},
    # 값 대조는 불가(GB 2763 이 스캔 PDF, 호주는 문서 다운로드 경로 미확인)하지만
    # 현행판이 바뀌었는지는 매일 확인한다 — watch=True 인 소스는 MRL 값을 만들지 않는다.
    "China": {"country": "CN", "kind": "regulation", "interval_days": 180,
              "authoritative": True, "watch": "GB 2763 이 스캔 PDF — 값 대조 불가, 개정만 감시"},
    "Australia": {"country": "AU", "kind": "regulation", "interval_days": 30,
                  "authoritative": True, "watch": "Schedule 20 문서 다운로드 경로 미확인 — 개정만 감시"},
    "Singapore": {"country": "SG", "kind": "regulation", "interval_days": 30,
                  "authoritative": True,
                  "watch": "제9부칙 등재 94종뿐 · 미등재 규칙 미확인 — 개정만 감시"},
    # 보류: 표준 원문 사이트가 해외 접근을 차단해 수집 자체가 불가(2026-08-20 실측).
    # 담당 연구사에게 실제 참고 사이트를 확인한 뒤 재개한다. deferred 인 소스는 수집을 시도하지
    # 않으므로 매 실행마다 실패 알림을 만들지 않는다.
    "Canada": {"country": "CA", "kind": "regulation", "interval_days": 14, "authoritative": True},
    "HongKong": {"country": "HK", "kind": "regulation", "interval_days": 30, "authoritative": True},
    "Indonesia": {"country": "ID", "kind": "regulation", "interval_days": 365, "authoritative": True,
                  "deferred": "표준 원문 사이트 해외 접근 차단 — 참고 사이트 확인 후 재개"},
    "WTO":   {"country": "INT", "kind": "earlywarn",  "interval_days": 1,   "authoritative": False},
}

# ---- 알림/보고 ----
REPORT_HOUR = int(os.getenv("REPORT_HOUR", "9"))   # 매일 발송 시각(시)
REPORT_TITLE = "수출농산물 농약기준 모니터링 운영보고"

# 이메일(SMTP) — 값이 있으면 활성화
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER)
SMTP_TO = [x.strip() for x in os.getenv("SMTP_TO", "").split(",") if x.strip()]

# 카카오 "나에게 보내기" — refresh token 있으면 활성화
KAKAO_REST_KEY = os.getenv("KAKAO_REST_KEY", "")
KAKAO_REFRESH_TOKEN = os.getenv("KAKAO_REFRESH_TOKEN", "")
KAKAO_CLIENT_SECRET = os.getenv("KAKAO_CLIENT_SECRET", "")   # 앱에서 Client Secret 사용 시 필수


def enabled_channels() -> list[str]:
    ch = []
    if SMTP_HOST and SMTP_TO:
        ch.append("email")
    if KAKAO_REST_KEY and KAKAO_REFRESH_TOKEN:
        ch.append("kakao")
    return ch
