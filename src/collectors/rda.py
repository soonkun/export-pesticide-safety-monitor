"""RDA 수출농산물 농약안전사용지침 collector (odcloud API).

지침 **전량**을 수집한다. 이전에는 cond[국가::EQ]/cond[작목::EQ] 로 (일본·EU) × (딸기·포도·배)
3개 조합만 받았는데, 실제 지침은 13개국 × 30여 작목 = 85개 조합(약 36,000행)이다.
우리가 대조할 수 있는 조합만 받으면 "지침의 나머지 97%는 어떤 상태인지 모른다"는 사실 자체가
화면에서 사라진다. 그래서 지침은 전부 적재하고, 대조 가능 여부는 비교 단계에서 따로 표시한다.

target_country 에는 지침 원문의 국가명(한국어: '일본','대만',…)을 그대로 넣는다.
"""
from __future__ import annotations

import json

from .. import db
from ..config import RDA_BASE, RDA_SERVICE_KEY, RAW_DIR
from ..http import AuthError, ParserError
from .base import BaseCollector, CollectResult, sha

EXPECTED_COLS = {"국가", "작목", "품목명", "외국", "한국"}
PER_PAGE = 1000


class RdaCollector(BaseCollector):
    name = "RDA"

    def collect(self, conn, s) -> CollectResult:
        if not RDA_SERVICE_KEY:
            raise AuthError("RDA_SERVICE_KEY 미설정(.env)")

        rows = self._fetch_all(s)
        if not rows:
            raise ParserError("RDA 지침 응답이 비어 있음")
        if not EXPECTED_COLS.issubset(rows[0].keys()):
            raise ParserError(f"RDA 컬럼 구조 변경 의심: {sorted(rows[0].keys())}")

        # 지침은 매 수집마다 전량 재적재(삭제된 행이 남지 않도록)
        conn.execute("DELETE FROM rda_guidelines")
        combos: set[tuple[str, str]] = set()
        for row in rows:
            country, commodity = (row.get("국가") or "").strip(), (row.get("작목") or "").strip()
            combos.add((country, commodity))
            conn.execute(
                "INSERT INTO rda_guidelines(target_country,commodity_ko,pesticide_ko,"
                "product_name,korea_mrl,foreign_cached_mrl,uses,retrieved_at)"
                " VALUES(?,?,?,?,?,?,?,?)"
                " ON CONFLICT(target_country,commodity_ko,product_name) DO UPDATE SET "
                "korea_mrl=excluded.korea_mrl,foreign_cached_mrl=excluded.foreign_cached_mrl,"
                "uses=excluded.uses,retrieved_at=excluded.retrieved_at",
                (country, commodity, None, row.get("품목명"),
                 row.get("한국"), row.get("외국"), row.get("용도"), db.now_iso()))

        content = "|".join(f"{c}/{p}" for c, p in sorted(combos))
        path = RAW_DIR / f"rda_{db.now_iso().replace(':','')}.json"
        path.write_text(json.dumps({"rows": len(rows), "combos": sorted(combos)},
                                   ensure_ascii=False), encoding="utf-8")
        db.add_snapshot(conn, source=self.name, url=RDA_BASE, retrieved_at=db.now_iso(),
                        http_status=200, content_type="application/json",
                        content_hash=sha(content), raw_file_path=str(path))
        return CollectResult(http_status=200, records_received=len(rows), records_valid=len(rows),
                             content_hash=sha(content),
                             schema_hash=sha(",".join(sorted(EXPECTED_COLS))))

    def _fetch_all(self, s) -> list[dict]:
        """지침 전량 페이지네이션. matchCount 를 다 받을 때까지."""
        out: list[dict] = []
        page = 1
        while page <= 200:                      # 폭주 방지 상한(현재 36 페이지 규모)
            params = {"page": page, "perPage": PER_PAGE, "returnType": "JSON",
                      "serviceKey": RDA_SERVICE_KEY}
            r = s.get(RDA_BASE, params=params, timeout=90)
            if r.status_code in (401, 403):
                raise AuthError(f"RDA 인증 실패 {r.status_code}")
            r.raise_for_status()
            j = r.json()
            data = j.get("data", [])
            out.extend(data)
            if not data or len(out) >= j.get("matchCount", j.get("totalCount", 0)):
                break
            page += 1
        return out
