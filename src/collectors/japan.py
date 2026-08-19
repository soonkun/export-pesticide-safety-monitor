"""Japan (Positive List / MRL) collector — FFCR 잔류농약기준 검색시스템(영문판).

공식 MHLW/CAA 원문 DB(jpn-pesticides-database.go.jp)는 해외 IP/봇을 403으로 차단해
자동 수집이 불가하다(STEP4 실측). 대신 후생노동성 고시(告示 370호)를 편집·공개하는
공익재단법인 일본식품화학연구진흥재단(FFCR) DB를 수집원으로 쓴다.

접근 흐름(실측 확정):
  1) GET  /front/?lng=en            → 세션에 영문 표기 설정
  2) POST /front/?m=p (첫 글자)     → 성분 목록 + pesticide_detail id
  3) GET  /front/pesticide_detail?id=N → 식품별 MRL 표
  ※ (2) 없이 (3)만 호출하면 첫 화면으로 리다이렉트된다(세션 상태 필요).

표에 해당 작물 행이 없으면 일본 포지티브리스트의 **일률기준 0.01 ppm**이 적용된다
(is_default=True 로 표기해 고시 개별기준과 구분).
"""
from __future__ import annotations

import re

from .. import db
from ..http import ParserError, SourceUnavailable
from ..masters import COMMODITIES, PESTICIDES
from ..models import Mrl, MrlKind
from ..normalize import parse_scalar
from .base import BaseCollector, CollectResult, sha

FFCR = "https://db.ffcr.or.jp/front/"
UNIFORM_LIMIT = 0.01          # 포지티브리스트 일률기준(ppm)

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_TD = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_LINK = re.compile(r'pesticide_detail\?id=(\d+)"[^>]*>(.*?)</a>', re.S)
_TAG = re.compile(r"<[^>]+>")


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", _TAG.sub("", s)).strip()


def parse_detail(page: str) -> dict[str, tuple[str, str]]:
    """상세 페이지 → {식품명: (본 기준, 경과조치 기한부 기준)}."""
    table: dict[str, tuple[str, str]] = {}
    for row in _ROW.findall(page):
        tds = [_text(c) for c in _TD.findall(row)]
        if len(tds) >= 2:
            table[tds[0]] = (tds[1], tds[4] if len(tds) > 4 else "")
    return table


def _match_id(index: dict[str, str], english: str) -> str | None:
    """FFCR 표기는 대문자이며 'ALDICARB and ALDOXYCARB' 처럼 합산 성분이 섞여 있다."""
    key = english.upper()
    if key in index:
        return index[key]
    for name, pid in index.items():
        if key in re.split(r"\s+AND\s+|\s*,\s*", name):
            return pid
    return None


class JapanCollector(BaseCollector):
    name = "Japan"

    def collect(self, conn, s) -> CollectResult:
        s.headers["User-Agent"] = "Mozilla/5.0 (compatible; pesticide-monitor)"
        try:
            r = s.get(FFCR + "?lng=en", timeout=40)
        except Exception as e:
            raise SourceUnavailable(f"FFCR 접속 실패: {e}")
        if r.status_code != 200 or len(r.text) < 5000:
            raise SourceUnavailable(f"FFCR HTTP {r.status_code} (len={len(r.text)})")

        by_letter: dict[str, list[tuple[str, str]]] = {}
        for ko, pm in PESTICIDES.items():
            by_letter.setdefault(pm["english"][0].lower(), []).append((ko, pm["english"]))

        stored = missing = 0
        seen_any = False
        for letter, names in sorted(by_letter.items()):
            lr = s.post(FFCR + "?m=p", data={"pesticide_class_eng": letter}, timeout=40)
            index = {_text(n).upper(): pid for pid, n in _LINK.findall(lr.text)}
            if not index:
                raise ParserError(f"FFCR 성분목록 파싱 실패(letter={letter}) — 페이지 구조 변경 의심")
            seen_any = True
            for pest_ko, en in names:
                pid = _match_id(index, en)
                if pid is None:
                    missing += 1
                    continue
                stored += self._detail(conn, s, pid, en)

        if not seen_any:
            raise ParserError("FFCR에서 대상 성분을 하나도 조회하지 못함")
        warn = [f"FFCR 목록에 없는 성분 {missing}건"] if missing else []
        return CollectResult(http_status=200, records_received=stored, records_valid=stored,
                             warnings=warn, content_hash=sha(str(stored)),
                             schema_hash=sha("FoodType|MRL|Basis|Note|TimeLimit"))

    def _detail(self, conn, s, pid: str, english: str) -> int:
        d = s.get(FFCR + "pesticide_detail?id=" + pid, timeout=40)
        table = parse_detail(d.text)
        if not table:
            raise ParserError(f"FFCR 상세표 파싱 실패(id={pid}, {english})")

        n = 0
        for commodity_ko, cm in COMMODITIES.items():
            jp = cm.get("japan_name")
            if not jp:
                continue
            cell = table.get(jp)
            note = None
            if cell is None:
                mrl = Mrl(MrlKind.NORMAL, value=UNIFORM_LIMIT, raw="0.01(일률기준)",
                          is_default=True)
                note = "고시 개별기준 없음 → 포지티브리스트 일률기준 0.01 적용"
            else:
                main, provisional = cell
                mrl = parse_scalar(main or provisional or None)
                if main and provisional:
                    # 경과조치: 괄호 안 기한까지는 기한부 값이 유효하고 그 뒤 본 기준으로 바뀐다.
                    note = f"경과조치 {provisional} 까지 유효 → 이후 {mrl.display()}"
            db.record_foreign_mrl(conn, source=self.name, pesticide_en=english,
                                  commodity_ko=commodity_ko, commodity_src=jp, mrl=mrl,
                                  note=note)
            n += 1
        return n
