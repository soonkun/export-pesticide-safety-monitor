"""Canada (Health Canada / PMRA) collector — MRL 공개 추출 CSV.

캐나다 보건부 해충관리규제국(PMRA)이 등록 MRL 전량을 CSV 로 공개한다(무키).
  https://pest-control.canada.ca/pesticide-registry-api/api/extract/mrl
컬럼: Chemical Common Name / Food Commodity / MRL Value (ppm) / Comments / Established Via
인코딩은 WINDOWS-1252 다(실측).

`Established Via` 에 **근거 문서와 날짜**가 들어 있어(예: "MRL Database (26 April 2026)
consulted via PMRL2026-02") 그대로 근거로 쓴다.

캐나다도 미국식 작물그룹(CROP GROUP 10 등) 표기를 쓰지만 **그룹 구성 작물 정의가 이 파일에
없다.** 근거 없이 그룹을 펼치면 다른 작물의 기준을 붙이게 되므로 **개별 품목 등재만 채택한다**
(대상 작목 기준 12성분 중 10~11건이 개별 등재라 실익이 크지 않다).
"""
from __future__ import annotations

import csv
import io
import re
from collections import defaultdict

from .. import db
from ..config import CANADA_MRL_URL, CANADA_SOURCE_PAGE
from ..http import ParserError, SourceUnavailable
from ..masters import COMMODITIES, PESTICIDES
from ..normalize import parse_scalar
from .base import BaseCollector, CollectResult, sha

EXPECTED_COLUMNS = {"Chemical Common Name", "Food Commodity", "MRL Value (ppm)"}
_DATE = re.compile(r"\(?(\d{1,2}\s+\w+\s+\d{4})\)?")


def parse_csv(text: str) -> list[dict]:
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows or not EXPECTED_COLUMNS.issubset(rows[0].keys()):
        raise ParserError(f"PMRA CSV 컬럼 구조 변경 의심: {sorted(rows[0].keys()) if rows else '빈 파일'}")
    return rows


def effective_date(established_via: str) -> str | None:
    """'MRL Database (26 April 2026) consulted via PMRL2026-02' → '26 April 2026'."""
    m = _DATE.search(established_via or "")
    return m.group(1) if m else None


class CanadaCollector(BaseCollector):
    name = "Canada"

    def collect(self, conn, s) -> CollectResult:
        try:
            r = s.get(CANADA_MRL_URL, timeout=180)
        except Exception as e:
            raise SourceUnavailable(f"PMRA MRL 추출 접속 실패: {e}")
        if r.status_code != 200 or len(r.content) < 100_000:
            raise SourceUnavailable(f"PMRA HTTP {r.status_code} ({len(r.content)}B)")
        r.encoding = "windows-1252"
        rows = parse_csv(r.text)

        # (성분, 품목) → {값}, 그리고 근거 문자열
        index: dict[tuple[str, str], set[str]] = defaultdict(set)
        basis: dict[tuple[str, str], str] = {}
        for row in rows:
            key = ((row["Chemical Common Name"] or "").strip().lower(),
                   (row["Food Commodity"] or "").strip())
            value = (row["MRL Value (ppm)"] or "").strip()
            if not value:
                continue
            index[key].add(value)
            basis[key] = (row.get("Established Via") or "").strip()

        stored = 0
        warnings: list[str] = []
        for pest_ko, pm in PESTICIDES.items():
            en = pm["english"]
            for commodity_ko, cm in COMMODITIES.items():
                names = cm.get("canada_name")
                if not names:
                    continue
                for name in ([names] if isinstance(names, str) else names):
                    values = index.get((en.lower(), name))
                    if not values:
                        continue
                    if len(values) > 1:
                        warnings.append(f"{en}/{commodity_ko}: 값 상충 {sorted(values)}")
                        break
                    src = basis.get((en.lower(), name), "")
                    db.record_foreign_mrl(
                        conn, source=self.name, pesticide_en=en, commodity_ko=commodity_ko,
                        commodity_src=name, mrl=parse_scalar(values.pop()),
                        effective_date=effective_date(src), source_url=CANADA_SOURCE_PAGE,
                        basis=f"PMRA MRL — {name}" + (f" · {src}" if src else ""))
                    stored += 1
                    break                      # 첫 번째로 등재된 표기를 쓴다(아시아배 우선)

        if not stored:
            raise ParserError("PMRA 자료에서 대상 (성분×작물) 기준을 하나도 찾지 못함")
        return CollectResult(http_status=200, records_received=stored, records_valid=stored,
                             warnings=sorted(set(warnings))[:5],
                             content_hash=sha(str(len(rows))),
                             schema_hash=sha(",".join(sorted(EXPECTED_COLUMNS))))
