"""EU DG SANTE Datalake collector (공개 API, 무키).

작물별 product-current-mrl-all-residues를 nextLink로 순회하여 전체 잔류물을 받고,
master 성분(영문명)과 매칭해 라이브 MRL을 저장한다(STEP4 확정 스펙).
"""
from __future__ import annotations

import time

from .. import db
from ..config import EU_API_VERSION, EU_BASE
from ..http import ParserError
from ..masters import COMMODITIES, PESTICIDES
from ..normalize import parse_eu
from .base import BaseCollector, CollectResult, sha

EXPECTED_FIELDS = {"PRODUCT_ID", "MRL_VALUE", "PESTICIDE_RESIDUE_NAME"}


def _iso(d: str | None) -> str | None:
    """EU 날짜 'DD/MM/YYYY' → 'YYYY-MM-DD'."""
    if not d or "/" not in d:
        return d
    try:
        dd, mm, yy = d.split("/")
        return f"{yy}-{mm}-{dd}"
    except ValueError:
        return d


class EuCollector(BaseCollector):
    name = "EU"

    def collect(self, conn, s) -> CollectResult:
        total = 0
        stored = 0
        for commodity_ko, cm in COMMODITIES.items():
            pid = cm.get("eu_product_id")
            if not pid:
                continue
            residues = self._all_residues(s, pid)
            total += len(residues)
            if residues and not EXPECTED_FIELDS.issubset(residues[0].keys()):
                raise ParserError(f"EU 스키마 변경 의심: {sorted(residues[0].keys())}")
            for pest_ko, pm in PESTICIDES.items():
                en = pm["english"]
                rec = self._find(residues, en)
                if rec is None:
                    continue
                mrl = parse_eu(rec.get("MRL_VALUE"), rec.get("MRL_LOD"), rec.get("MRL_DISPLAY"))
                # 근거: 이 값을 실제로 읽어온 API 질의 URL(재확인 가능) + 각주
                url = (f"{EU_BASE}/product-current-mrl-all-residues?PRODUCT_ID={pid}"
                       f"&format=json&api-version={EU_API_VERSION}")
                db.record_foreign_mrl(conn, source=self.name, pesticide_en=en,
                                      commodity_ko=commodity_ko, commodity_src=cm["eu_code"], mrl=mrl,
                                      source_url=url, basis=(rec.get("MRL_FOOTNOTE") or ""))
                stored += 1

        # 유효성분 등록/승인 상태 (수출 가부 판정용)
        self._collect_registrations(conn, s)
        return CollectResult(http_status=200, records_received=total, records_valid=stored,
                             content_hash=sha(str(total)),
                             schema_hash=sha(",".join(sorted(EXPECTED_FIELDS))))

    def _collect_registrations(self, conn, s) -> None:
        url = f"{EU_BASE}/active-substances"
        for pest_ko, pm in PESTICIDES.items():
            en = pm["english"]
            r = self._get_retry(s, url, {"substance_name": en, "format": "json",
                                         "api-version": EU_API_VERSION})
            try:
                arr = (r.json().get("value") if isinstance(r.json(), dict) else r.json()) or []
            except Exception:
                continue
            rec = next((a for a in arr
                        if (a.get("substance_name") or "").lower() == en.lower()), None)
            if not rec:
                continue
            db.record_registration(conn, source=self.name, pesticide_en=en,
                                   status=rec.get("substance_status"),
                                   approval_date=_iso(rec.get("approval_date")),
                                   expiry_date=_iso(rec.get("expiry_date")))

    @staticmethod
    def _find(residues: list[dict], english: str):
        el = english.lower()
        for r in residues:
            nm = (r.get("PESTICIDE_RESIDUE_NAME") or "").lower()
            if nm == el or nm.startswith(el + " ") or nm.startswith(el + "("):
                return r
        return None

    def _all_residues(self, s, pid: int) -> list[dict]:
        url = f"{EU_BASE}/product-current-mrl-all-residues"
        params = {"PRODUCT_ID": pid, "format": "json", "api-version": EU_API_VERSION}
        out: list[dict] = []
        for _page in range(30):
            r = self._get_retry(s, url, params)
            j = r.json()
            out.extend(j.get("value", []))
            nxt = j.get("nextLink")
            if not nxt:
                break
            url, params = nxt, None      # nextLink는 완전한 URL
        return out

    @staticmethod
    def _get_retry(s, url, params, tries=5):
        last = None
        for i in range(tries):
            r = s.get(url, params=params, timeout=40)
            if r.status_code < 500:
                return r
            last = r
            time.sleep(1.2)             # 간헐적 500 → 재시도(STEP4 관측)
        return last
