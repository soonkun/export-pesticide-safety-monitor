"""Hong Kong (CFS) collector — Pesticide Residues in Food Regulation (Cap. 132CM) Schedule 1.

식품안전센터(CFS)의 Pesticide MRL Database 조회 시스템을 쓴다. bulk/API 는 없고
이용약관 동의 → 성분 선택 → 식품 선택 → 조회 의 세션 기반 폼이다(실측 확정):
  1) POST mrl_select_pesticide.php (ShowallAction=Y)  → 성분 360종 + pest_id
  2) POST mrl_select_food.php      (ShowallAction=Y)  → 식품 422종 + food_id
  3) POST mrl_report.php           (pest_id, food_id) → 해당 조합의 MRL 행

food_id 는 **Codex 품목코드**(예: Pear = 'FP 0230') 라서 표기가 안정적이다.
코드를 코드베이스에 박아두지 않고 매 수집마다 사이트 목록에서 해석한다(§30).
"""
from __future__ import annotations

import re
import time

from .. import db
from ..config import HK_BASE, HK_SOURCE_PAGE
from ..http import ParserError, SourceUnavailable
from ..masters import COMMODITIES, PESTICIDES
from ..normalize import parse_scalar
from .base import BaseCollector, CollectResult, sha

_OPTION = re.compile(r"tosubmit\s*\('([^']+)'\);\s*\">(.*?)</a>", re.S)
_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
_TAG = re.compile(r"<[^>]+>")
REQUEST_PAUSE = 0.3           # 정부 사이트에 대한 최소한의 예의 (72회 요청)


def _text(x: str) -> str:
    return re.sub(r"\s+", " ", _TAG.sub("", x)).strip()


def parse_options(page: str) -> dict[str, str]:
    """선택 목록 페이지 → {표시명: id}."""
    return {_text(name): ident for ident, name in _OPTION.findall(page)}


def parse_report(page: str) -> list[tuple[str, str]]:
    """조회 결과 → [(식품 설명, MRL 문자열)]. 표 머리글·안내문은 버린다."""
    out = []
    for row in _ROW.findall(page):
        cells = [_text(c) for c in _CELL.findall(row)]
        # 데이터 행: [항목번호, 조항, 성분, 잔류물정의, 식품설명, MRL]
        if len(cells) >= 6 and re.fullmatch(r"\d+", cells[0]) and cells[-1]:
            out.append((cells[-2], cells[-1]))
    return out


class HongKongCollector(BaseCollector):
    name = "HongKong"

    def _post(self, s, path: str, **data) -> str:
        r = s.post(HK_BASE + path, data={"acceptTC": "true", **data}, timeout=60)
        if r.status_code != 200:
            raise SourceUnavailable(f"CFS {path} HTTP {r.status_code}")
        return r.text

    def collect(self, conn, s) -> CollectResult:
        s.headers["User-Agent"] = "Mozilla/5.0 (compatible; pesticide-monitor)"
        try:
            self._post(s, "mrl_preinput.php")
        except SourceUnavailable:
            raise
        except Exception as e:
            raise SourceUnavailable(f"CFS 접속 실패: {e}")

        pests = parse_options(self._post(s, "mrl_select_pesticide.php",
                                         step="1", ShowallPest="Y", ShowallAction="Y", keyword=""))
        if not pests:
            raise ParserError("CFS 성분 목록 파싱 실패 — 페이지 구조 변경 의심")
        foods = parse_options(self._post(s, "mrl_select_food.php", step="2",
                                         pest_id=next(iter(pests.values())),
                                         ShowallFood="Y", ShowallAction="Y", foodkeyword=""))
        if not foods:
            raise ParserError("CFS 식품 목록 파싱 실패 — 페이지 구조 변경 의심")

        stored = 0
        warnings: list[str] = []
        for pest_ko, pm in PESTICIDES.items():
            en = pm["english"]
            pest_id = pests.get(en)
            if pest_id is None:
                warnings.append(f"{en}: CFS 목록에 없음")
                continue
            for commodity_ko, cm in COMMODITIES.items():
                food = cm.get("hk_name")
                if not food:
                    continue
                food_id = foods.get(food)
                if food_id is None:
                    warnings.append(f"{commodity_ko}: CFS 식품 '{food}' 없음")
                    continue
                page = self._post(s, "mrl_report.php", step="2", pest_id=pest_id,
                                  food_id=food_id, last_step="mrl_select_food.php")
                time.sleep(REQUEST_PAUSE)
                rows = parse_report(page)
                if not rows:
                    continue                       # 그 조합에 기준 없음 → 값 만들지 않는다
                values = {v for _d, v in rows}
                if len(values) > 1:
                    warnings.append(f"{en}/{commodity_ko}: 기준 상충 {sorted(values)}")
                    continue
                desc, value = rows[0]
                db.record_foreign_mrl(
                    conn, source=self.name, pesticide_en=en, commodity_ko=commodity_ko,
                    commodity_src=f"{food} ({food_id})", mrl=parse_scalar(value),
                    source_url=HK_SOURCE_PAGE,
                    basis=f"Cap. 132CM Schedule 1 — {desc}")
                stored += 1

        if not stored:
            raise ParserError("CFS 에서 대상 (성분×작물) 기준을 하나도 얻지 못함")
        return CollectResult(http_status=200, records_received=stored, records_valid=stored,
                             warnings=sorted(set(warnings))[:5],
                             content_hash=sha(str(stored)),
                             schema_hash=sha("item,provision,pesticide,residue,food,mrl"))
