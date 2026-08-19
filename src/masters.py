"""pesticide_master / commodity_master (§10·§11).

PoC 시드: STEP4 검증대상 + RDA 딸기 데이터에서 확인된 성분 위주.
식별자는 **검증된 값만** 넣는다(codex_pid는 Codex 인덱스에서 실제 확인한 것만).
미검증 항목은 None으로 두어 추측을 배제한다. 매핑은 담당자 승인(§12) 후 확장한다.
"""
from __future__ import annotations

from .models import Mapping

# korean_name → {english, codex_pid, cas}
#   codex_pid: FAO Codex pesticide index에서 실측한 값만 기입(없으면 None → Codex 비교 스킵)
PESTICIDES: dict[str, dict] = {
    "플루디옥소닐":        {"english": "Fludioxonil",        "codex_pid": 211, "cas": "131341-86-1"},
    "아족시스트로빈":      {"english": "Azoxystrobin",       "codex_pid": 229, "cas": "215934-32-0"},
    "디페노코나졸":        {"english": "Difenoconazole",     "codex_pid": 224, "cas": "119446-68-3"},
    "보스칼리드":          {"english": "Boscalid",           "codex_pid": 221, "cas": "188425-85-6"},
    "사이프로디닐":        {"english": "Cyprodinil",         "codex_pid": 207, "cas": "121552-61-2"},
    "아세타미프리드":      {"english": "Acetamiprid",        "codex_pid": 246, "cas": "135410-20-7"},
    "아바멕틴":            {"english": "Abamectin",          "codex_pid": 177, "cas": "71751-41-2"},
    "클로란트라닐리프롤":  {"english": "Chlorantraniliprole","codex_pid": 230, "cas": "500008-45-7"},
    "델타메트린":          {"english": "Deltamethrin",       "codex_pid": 135, "cas": "52918-63-5"},
    "이미다클로프리드":    {"english": "Imidacloprid",       "codex_pid": 206, "cas": "138261-41-3"},
    "클로르페나피르":      {"english": "Chlorfenapyr",       "codex_pid": 254, "cas": "122453-73-0"},
    "스피네토람":          {"english": "Spinetoram",         "codex_pid": None, "cas": "935545-74-7"},
}

# 별칭(표기 변형) → canonical
PESTICIDE_ALIASES: dict[str, str] = {
    "플루디옥소닐(액상수화제)": "플루디옥소닐",
}

# korean_name → 매핑. codex_group=True 면 개별 commodity 없이 그룹으로 비교(사과/배→Pome fruits).
COMMODITIES: dict[str, dict] = {
    "딸기": {"english": "Strawberry", "eu_product_id": 39, "eu_code": "0152000",
             "codex_name": "Strawberry",           "codex_group": False, "japan_name": "Strawberry"},
    "포도": {"english": "Grape",      "eu_product_id": 37, "eu_code": "0151010",
             "codex_name": "Grapes",               "codex_group": False, "japan_name": "Grape"},
    "사과": {"english": "Apple",      "eu_product_id": 23, "eu_code": "0130010",
             "codex_name": "Pome fruits (group)",  "codex_group": True,  "japan_name": "Apple"},
    "배":   {"english": "Pear",       "eu_product_id": 24, "eu_code": "0130020",
             "codex_name": "Pome fruits (group)",  "codex_group": True,  "japan_name": "Pear"},
}


def lookup_pesticide(korean_name: str) -> tuple[dict | None, Mapping]:
    key = (korean_name or "").strip()
    if key in PESTICIDES:
        return PESTICIDES[key], Mapping.EXACT
    if key in PESTICIDE_ALIASES:
        return PESTICIDES[PESTICIDE_ALIASES[key]], Mapping.ALIAS_MATCH
    return None, Mapping.UNMAPPED


def lookup_commodity(korean_name: str) -> tuple[dict | None, Mapping]:
    key = (korean_name or "").strip()
    if key in COMMODITIES:
        return COMMODITIES[key], Mapping.EXACT
    return None, Mapping.UNMAPPED


# ---- WTO ePing 회원국 표기 → (약어, ISO2) ----
# 보고서에는 "United States of America" 대신 🇺🇸 USA 로만 찍는다. 본문에서 "미국은~"으로
# 서술할 것이므로 표/목록에서는 식별만 되면 충분하다.
MEMBERS: dict[str, tuple[str, str]] = {
    "United States of America": ("USA", "US"),
    "United Kingdom": ("UK", "GB"),
    "European Union": ("EU", "EU"),
    "EU": ("EU", "EU"),           # source 이름으로도 조회된다

    "Korea, Republic of": ("KR", "KR"),
    "Saudi Arabia, Kingdom of": ("SA", "SA"),
    "Chinese Taipei": ("TW", "TW"),
    "Russian Federation": ("RU", "RU"),
    "Viet Nam": ("VN", "VN"),
    "New Zealand": ("NZ", "NZ"),
    "El Salvador": ("SV", "SV"),
    "Türkiye": ("TR", "TR"),
    "Japan": ("JP", "JP"), "Brazil": ("BR", "BR"), "Canada": ("CA", "CA"),
    "Australia": ("AU", "AU"), "China": ("CN", "CN"), "Israel": ("IL", "IL"),
    "Switzerland": ("CH", "CH"), "Norway": ("NO", "NO"), "Poland": ("PL", "PL"),
    "Chile": ("CL", "CL"), "Colombia": ("CO", "CO"), "Panama": ("PA", "PA"),
    "Uruguay": ("UY", "UY"), "Thailand": ("TH", "TH"), "Malaysia": ("MY", "MY"),
    "Indonesia": ("ID", "ID"), "Philippines": ("PH", "PH"), "Morocco": ("MA", "MA"),
    "Kazakhstan": ("KZ", "KZ"), "Ukraine": ("UA", "UA"), "Kenya": ("KE", "KE"),
    "Uganda": ("UG", "UG"), "Tanzania": ("TZ", "TZ"), "Rwanda": ("RW", "RW"),
    "Burundi": ("BI", "BI"),
}


def member_label(name: str | None) -> str:
    """'United Kingdom' → '🇬🇧 UK'. 표에 없는 회원국은 원문 그대로(깃발 없이)."""
    abbr, iso = MEMBERS.get((name or "").strip(), ("", ""))
    if not iso:
        return (name or "?").strip()
    flag = "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in iso)
    return f"{flag} {abbr}"
