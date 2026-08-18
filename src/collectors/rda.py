"""RDA 수출농산물 농약안전사용지침 collector (odcloud API).

cond[국가::EQ]/cond[작목::EQ] 필터로 대상 (국가×작목)만 수집(STEP4 확정).
각 행의 한국(국내) / 외국(캐시된 수입국) MRL을 원문 그대로 저장한다.
"""
from __future__ import annotations

import json

from .. import db
from ..config import RDA_BASE, RDA_SERVICE_KEY, RAW_DIR
from ..http import AuthError, ParserError
from ..masters import COMMODITIES
from .base import BaseCollector, CollectResult, sha

# 우리 소스 라벨 → RDA 데이터의 국가 값
RDA_COUNTRY = {"EU": "EU", "Japan": "일본"}
EXPECTED_COLS = {"국가", "작목", "품목명", "외국", "한국"}


class RdaCollector(BaseCollector):
    name = "RDA"

    def collect(self, conn, s) -> CollectResult:
        if not RDA_SERVICE_KEY:
            raise AuthError("RDA_SERVICE_KEY 미설정(.env)")

        total = 0
        blob_parts: list[str] = []
        first_row = None
        for target, country_ko in RDA_COUNTRY.items():
            for commodity_ko in COMMODITIES:
                rows = self._fetch(s, country_ko, commodity_ko)
                for row in rows:
                    if first_row is None:
                        first_row = row
                    conn.execute(
                        "INSERT INTO rda_guidelines(target_country,commodity_ko,pesticide_ko,"
                        "product_name,korea_mrl,foreign_cached_mrl,uses,retrieved_at)"
                        " VALUES(?,?,?,?,?,?,?,?)"
                        " ON CONFLICT(target_country,commodity_ko,product_name) DO UPDATE SET "
                        "korea_mrl=excluded.korea_mrl,foreign_cached_mrl=excluded.foreign_cached_mrl,"
                        "uses=excluded.uses,retrieved_at=excluded.retrieved_at",
                        (target, commodity_ko, None, row.get("품목명"),
                         row.get("한국"), row.get("외국"), row.get("용도"), db.now_iso()))
                    total += 1
                blob_parts.append(f"{target}/{commodity_ko}:{len(rows)}")

        if first_row is not None and not EXPECTED_COLS.issubset(first_row.keys()):
            raise ParserError(f"RDA 컬럼 구조 변경 의심: {sorted(first_row.keys())}")

        content = "|".join(blob_parts)
        path = RAW_DIR / f"rda_{db.now_iso().replace(':','')}.json"
        path.write_text(json.dumps({"summary": content}, ensure_ascii=False), encoding="utf-8")
        db.add_snapshot(conn, source=self.name, url=RDA_BASE, retrieved_at=db.now_iso(),
                        http_status=200, content_type="application/json",
                        content_hash=sha(content), raw_file_path=str(path))
        return CollectResult(http_status=200, records_received=total, records_valid=total,
                             content_hash=sha(content), schema_hash=sha(",".join(sorted(EXPECTED_COLS))))

    def _fetch(self, s, country_ko: str, commodity_ko: str) -> list[dict]:
        out: list[dict] = []
        page = 1
        while True:
            params = {
                "page": page, "perPage": 200, "returnType": "JSON",
                "serviceKey": RDA_SERVICE_KEY,
                "cond[국가::EQ]": country_ko,
                "cond[작목::EQ]": commodity_ko,
            }
            r = s.get(RDA_BASE, params=params, timeout=40)
            if r.status_code in (401, 403):
                raise AuthError(f"RDA 인증 실패 {r.status_code}")
            r.raise_for_status()
            j = r.json()
            data = j.get("data", [])
            out.extend(data)
            match = j.get("matchCount", j.get("totalCount", 0))
            if page * 200 >= match or not data:
                break
            page += 1
        return out
