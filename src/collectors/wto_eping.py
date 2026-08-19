"""WTO ePing SPS collector — 변경 예고(Early warning) 전용 (§16).

/eping/notifications/search 에서 SPS 통보문을 받아 저장한다.
MRL 기준값으로 쓰지 않는다. 'maximum residue' 관련만 선별.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from .. import db
from ..config import WTO_API_KEY, WTO_BASE
from ..http import AuthError
from .base import BaseCollector, CollectResult, sha

FREE_TEXTS = ["maximum residue", "pesticide"]


class WtoCollector(BaseCollector):
    name = "WTO"

    def collect(self, conn, s) -> CollectResult:
        if not WTO_API_KEY:
            raise AuthError("WTO_API_KEY 미설정(.env)")

        since = (date.today() - timedelta(days=365)).isoformat()
        seen: dict[str, dict] = {}
        for ft in FREE_TEXTS:
            for page in range(1, 4):
                params = {
                    "language": 1, "pageSize": 100, "page": page,
                    "freeText": ft, "distributionDateFrom": since,
                    "subscription-key": WTO_API_KEY,
                }
                r = s.get(f"{WTO_BASE}/notifications/search", params=params, timeout=40)
                if r.status_code in (401, 403):
                    raise AuthError(f"WTO 인증 실패 {r.status_code}")
                r.raise_for_status()
                j = r.json()
                recs = (j.get("items") if isinstance(j, dict) else j) or []
                for n in recs:
                    if (n.get("area") or "").upper() != "SPS":
                        continue
                    seen[str(n.get("id"))] = n
                if len(recs) < 100:
                    break

        latest = None
        for nid, n in seen.items():
            dd = n.get("distributionDate")
            latest = max(latest, dd) if latest and dd else (dd or latest)
            conn.execute(
                "INSERT OR REPLACE INTO sps_notifications(id,area,notif_type,member,"
                "distribution_date,comment_deadline,entry_into_force,document_symbol,"
                "title,products,keywords,link,retrieved_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (nid, n.get("area"), n.get("notificationType"), n.get("notifyingMember"),
                 n.get("distributionDate"), n.get("commentDeadlineDate"),
                 n.get("proposedEntryIntoForceDate"),   # ISO 날짜만(텍스트는 시행일 계산 불가)
                 (n.get("documentSymbol") or "").strip(),
                 n.get("titlePlain") or n.get("title"),
                 n.get("productsFreeTextPlain") or "",
                 ",".join(k.get("name", "") for k in (n.get("spsKeywords") or [])),
                 n.get("linkToNotification"), db.now_iso()))

        conn.commit()
        scanned, found = scan_attachments(conn, s)
        warn = [f"첨부 {scanned}건 스캔 · 대상 성분 언급 {found}건"] if scanned else []
        return CollectResult(http_status=200, records_received=len(seen), records_valid=len(seen),
                             data_date=(latest[:10] if latest else None), warnings=warn,
                             content_hash=sha(str(len(seen))), schema_hash=sha("eping.notification"))


# ---------------------------------------------------------------- 첨부문서 스캔
# ePing API 가 주는 title/products 에는 성분명이 없는 나라가 많다.
#   예) 일본 G/SPS/N/JPN/1417 title: "Revision of the Specifications and Standards for
#       Foods, Food Additives, Etc." · products: HS 코드 · keywords: MRL
#   성분명은 첨부 .docx 본문 "6. Description of content: ... Pesticide: Mepronil." 에만 있다.
# 실측: MRL 통보 202건 중 성분명이 구조화 필드에 드러난 것은 5건뿐.
# 첨부는 스캔 가능한 Office 문서(PK zip)이므로 본문에서 대상 성분명을 찾는다.
import io
import zipfile

MRL_KEYWORD = "maximum residue"
SCAN_LIMIT = 120          # 1회 실행당 새로 받을 첨부 수 상한 (첫 실행 이후엔 증분만)


def _docx_text(blob: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", xml))


def scan_attachments(conn, s) -> tuple[int, int]:
    """아직 안 본 MRL 통보문의 첨부를 받아 대상 성분명을 찾아 캐시한다. (스캔수, 적중수)"""
    from ..masters import PESTICIDES
    ens = {pm["english"].lower(): pm["english"] for pm in PESTICIDES.values()}
    pending = conn.execute(
        "SELECT n.document_symbol, n.link FROM sps_notifications n "
        "LEFT JOIN sps_attachments a ON a.document_symbol = n.document_symbol "
        "WHERE a.document_symbol IS NULL AND n.link IS NOT NULL "
        "  AND lower(COALESCE(n.keywords,'')) LIKE ? "
        "ORDER BY n.distribution_date DESC LIMIT ?",
        (f"%{MRL_KEYWORD}%", SCAN_LIMIT)).fetchall()

    scanned = found = 0
    for row in pending:
        status, names = "OK", ""
        try:
            text = _docx_text(s.get(row["link"], timeout=45).content).lower()
            hits = sorted({v for k, v in ens.items() if k in text})
            names = ",".join(hits)
            if hits:
                found += 1
        except Exception as e:                 # 첨부 형식이 다르거나 받기 실패 — 캐시해 재시도 방지
            status = f"FAIL:{type(e).__name__}"
        conn.execute(
            "INSERT OR REPLACE INTO sps_attachments(document_symbol,link,fetched_at,status,pesticides)"
            " VALUES(?,?,?,?,?)",
            (row["document_symbol"], row["link"], db.now_iso(), status, names))
        scanned += 1
    conn.commit()
    return scanned, found
