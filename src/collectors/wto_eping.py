"""WTO ePing SPS collector — 변경 예고(Early warning) 전용 (§16).

/eping/notifications/search 에서 SPS 통보문을 받아 저장한다.
MRL 기준값으로 쓰지 않는다. 'maximum residue' 관련만 선별.
"""
from __future__ import annotations

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
                 n.get("proposedEntryIntoForceDate") or n.get("proposedEntryIntoForceDateText"),
                 (n.get("documentSymbol") or "").strip(),
                 n.get("titlePlain") or n.get("title"),
                 n.get("productsFreeTextPlain") or "",
                 ",".join(k.get("name", "") for k in (n.get("spsKeywords") or [])),
                 n.get("linkToNotification"), db.now_iso()))

        return CollectResult(http_status=200, records_received=len(seen), records_valid=len(seen),
                             data_date=(latest[:10] if latest else None),
                             content_hash=sha(str(len(seen))), schema_hash=sha("eping.notification"))
