"""USA (EPA) collector — 40 CFR Part 180 tolerances, eCFR 공개 API.

미국 현행 잔류허용기준은 연방규정 40 CFR 180 그 자체다. eCFR 이 규정 전문을 XML로
공개하므로(무키) 원문을 받아 파싱한다.

어려운 점은 EPA가 작물을 **작물그룹(Crop Group)** 으로 묶어 허용량을 정한다는 것이다.
예: 사과의 기준은 'Apple' 행이 아니라 'Fruit, pome, group 11-10' 행에 있을 수 있다.
그룹의 구성 작물은 §180.41 에 규정 자체로 정의돼 있으므로(추측 아님) 이를 색인해서 해석한다.

해석 규칙(§30 — 확실할 때만 값을 쓴다):
  1) 허용량 표의 commodity 가 대상 작물명과 정확히 일치하면 채택.
  2) 그렇지 않으면 'group 11-10' / 'subgroup 13-07F' 를 가리키는 행 중,
     그 그룹에 대상 작물이 속하고 'except ...' 로 제외되지 않은 행을 채택.
  3) 후보가 여러 개인데 값이 서로 다르면 **채택하지 않고 경고만 남긴다.**
"""
from __future__ import annotations

import html
import re

from .. import db
from ..config import USA_CFR_DATE_URL, USA_CFR_PART_URL, USA_SECTION_URL
from ..http import ParserError, SourceUnavailable
from ..masters import COMMODITIES, PESTICIDES
from ..normalize import parse_scalar
from .base import BaseCollector, CollectResult, sha

_TAG = re.compile(r"<[^>]+>")
_SECTION = re.compile(r'<DIV8 N="([^"]+)"[^>]*>\s*<HEAD>(.*?)</HEAD>', re.S)
_GROUP_REF = re.compile(r"\b(?:sub)?groups?\s+([0-9]+(?:-[0-9]+)?[A-Z]?)", re.I)
_SUP = re.compile(r"<sup>.*?</sup>", re.S)      # 각주 표식 (예: "Pear, Asian <sup>1</sup>")


def _txt(x: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", _TAG.sub("", x))).strip()


_ITALIC = re.compile(r"<I>.*?</I>", re.S)


def _norm_commodity(name: str) -> str:
    """허용량 표의 commodity 표기 정규화.

    쉼표 뒤를 **자르지 않는다** — 'Apple, wet pomace'(사과박)는 신선 사과와 다른 품목이고,
    'Grape, raisin'(건포도)도 마찬가지다. 잘라내면 가공품 기준을 신선 과실에 붙이게 된다.
    """
    return re.sub(r"\s+", " ", _txt(_SUP.sub("", name)).lower()).strip(" .,;:")


def _norm_group_item(raw: str) -> str:
    """§180.41 구성작물 항목 정규화.

    학명은 <I> 로 감싸여 있으므로 **첫 <I> 앞까지**가 작물명이다.
      'Apple, <I>Malus domestica</I> Borkh.'          → 'apple'
      'Pear, Asian, <I>Pyrus pyrifolia</I> ...'       → 'pear, asian'
    쉼표로 자르면 'pear, asian'(아시아배)이 'pear'로 뭉개져 한국 배의 기준을 놓친다.
    학명이 없는 소그룹 목록('beet, garden')은 이름 자체가 도치 표기이므로 그대로 둔다.
    """
    m = _ITALIC.search(raw)
    s = raw[: m.start()] if m else raw
    s = re.sub(r"\([^)]*\)", " ", _txt(s).lower())
    s = s.replace("(", " ").replace(")", " ")   # 'Apple (<I>학명</I>)' 은 여는 괄호만 남는다
    return re.sub(r"\s+", " ", s).strip(" .,;:")


def build_group_index(part_xml: str) -> dict[str, set[str]]:
    """§180.41 → {그룹라벨: {구성 작물명}}. 규정에 적힌 것만 넣는다."""
    m = re.search(r'<DIV8 N="180\.41".*?(?=<DIV8 |\Z)', part_xml, re.S)
    if not m:
        raise ParserError("40 CFR 180.41(작물그룹표)를 찾지 못함 — 규정 구조 변경 의심")
    sec = m.group()
    index: dict[str, set[str]] = {}

    def add(label: str, commodity: str) -> None:
        c = _norm_group_item(commodity)
        if c and not c.startswith("cultivars"):
            index.setdefault(label.upper(), set()).add(c)

    # (A) <EXTRACT> 형태: "Crop Group 11-10: Pome Fruit Group—Commodities" + <FP-1> 목록
    for ex in re.findall(r"<EXTRACT>.*?</EXTRACT>", sec, re.S):
        head = re.search(r"<HD1>(.*?)</HD1>", ex, re.S)
        if not head:
            continue
        gm = re.search(r"Crop (?:Sub)?[Gg]roup ([0-9]+(?:-[0-9]+)?[A-Z]?)", _txt(head.group(1)))
        if not gm:
            continue
        for item in re.findall(r"<FP-1>(.*?)</FP-1>", ex, re.S):
            add(gm.group(1), item)

    # (B) <TABLE> 형태: 본표(작물 + 소속 소그룹) / 소그룹표(대표작물 + 구성작물)
    for tbl in re.findall(r"<TABLE.*?</TABLE>", sec, re.S):
        cap_m = re.search(r"<CAPTION>(.*?)</CAPTION>", tbl, re.S)
        cap = _txt(cap_m.group(1)) if cap_m else ""
        gm = re.search(r"Crop Group ([0-9]+(?:-[0-9]+)?)", cap)
        current = gm.group(1) if gm else None
        is_sub = "ubgroup" in cap
        for tr in re.findall(r"<TR>(.*?)</TR>", tbl, re.S):
            tds = [_txt(c) for c in re.findall(r"<TD[^>]*>(.*?)</TD>", tr, re.S)]
            if len(tds) == 1:
                sm = re.match(r"Crop Subgroup ([0-9]+(?:-[0-9]+)?[A-Z]?)\.", tds[0])
                if sm:
                    current = sm.group(1)
                continue
            if len(tds) < 2 or not current:
                continue
            if is_sub:
                for c in tds[1].split(";"):
                    add(current, c)
            else:
                add(current, tds[0])
                for sg in re.findall(r"[0-9]+(?:-[0-9]+)?[A-Z]", tds[1]):
                    add(sg, tds[0])
    return index


def parse_tolerances(section_xml: str) -> list[tuple[str, str]]:
    """성분 절 → [(commodity 표기, ppm 문자열)]."""
    out = []
    for tbl in re.findall(r"<TABLE.*?</TABLE>", section_xml, re.S):
        for tr in re.findall(r"<TR>(.*?)</TR>", tbl, re.S):
            tds = [_txt(_SUP.sub("", c)) for c in re.findall(r"<TD[^>]*>(.*?)</TD>", tr, re.S)]
            if len(tds) >= 2 and tds[0] and re.match(r"^[\d.]+$", tds[1].replace(",", "")):
                out.append((tds[0], tds[1]))
    return out


def resolve(rows: list[tuple[str, str]], crop: str | list[str],
            groups: dict[str, set[str]]) -> tuple[str, str] | None:
    """대상 작물의 허용량 1건을 규정에서 해석. 애매하면 None.

    crop 에 표기를 여러 개 줄 수 있다 — 같은 작물이 작물그룹 세대에 따라 다르게 불린다.
    예: 아시아배는 group 11 에서 'Pear, oriental', group 11-10 에서 'Pear, Asian'.
    """
    targets = [_norm_commodity(c) for c in ([crop] if isinstance(crop, str) else crop)]

    direct = [(c, v) for c, v in rows if _norm_commodity(c) in targets]
    if direct:
        return direct[0]

    hits: list[tuple[str, str]] = []
    for commodity, value in rows:
        low = commodity.lower()
        refs = _GROUP_REF.findall(commodity)
        if not refs:
            continue
        members = set().union(*(groups.get(r.upper(), set()) for r in refs)) if refs else set()
        matched = [t for t in targets if t in members]
        if not matched:
            continue
        # "..., except fuzzy kiwifruit" 처럼 제외된 작물이면 이 행은 쓰지 않는다
        excepts = re.findall(r"except ([^,;]+)", low)
        if any(t in e for t in matched for e in excepts):
            continue
        hits.append((commodity, value))

    if not hits:
        return None
    values = {v for _c, v in hits}
    if len(values) > 1:
        return None                    # 서로 다른 값 → 담당자 확인 대상, 자동 채택 금지
    return hits[0]


class UsaCollector(BaseCollector):
    name = "USA"

    def collect(self, conn, s) -> CollectResult:
        try:
            d = s.get(USA_CFR_DATE_URL, timeout=60)
            date = next(x["latest_issue_date"] for x in d.json()["titles"] if x["number"] == 40)
        except Exception as e:
            raise SourceUnavailable(f"eCFR 개정일 조회 실패: {e}")

        r = s.get(USA_CFR_PART_URL.format(date=date), timeout=180)
        if r.status_code != 200 or len(r.text) < 100_000:
            raise SourceUnavailable(f"eCFR 40 CFR 180 응답 이상 (HTTP {r.status_code}, {len(r.text)}B)")
        part = r.text

        groups = build_group_index(part)
        sections = {n: m for n, m in _SECTION.findall(part)}
        bodies = {n: b for n, b in
                  ((n, re.search(rf'<DIV8 N="{re.escape(n)}".*?(?=<DIV8 |\Z)', part, re.S))
                   for n in sections) if b}

        stored = 0
        warnings: list[str] = []
        for pest_ko, pm in PESTICIDES.items():
            en = pm["english"]
            cfr_name = pm.get("usa_name", en)      # CFR 등재명이 다른 성분(예: 아바멕틴)
            sec_no = next((n for n, head in sections.items()
                           if re.search(rf"\b{re.escape(cfr_name)}\b", _txt(head), re.I)), None)
            if sec_no is None:
                warnings.append(f"{en}: 40 CFR 180 에 해당 절 없음(검색명 {cfr_name})")
                continue
            rows = parse_tolerances(bodies[sec_no].group())
            if not rows:
                warnings.append(f"{en}: §{sec_no} 허용량 표 파싱 결과 0건")
                continue
            url = USA_SECTION_URL.format(section=sec_no)
            for commodity_ko, cm in COMMODITIES.items():
                crop = cm.get("usa_name")
                if not crop:
                    continue
                hit = resolve(rows, crop, groups)
                if hit is None:
                    continue
                commodity_txt, ppm = hit
                db.record_foreign_mrl(
                    conn, source=self.name, pesticide_en=en, commodity_ko=commodity_ko,
                    commodity_src=commodity_txt, mrl=parse_scalar(ppm), source_url=url,
                    basis=f"40 CFR §{sec_no} — {commodity_txt}")
                stored += 1

        if not stored:
            raise ParserError("40 CFR 180 에서 대상 (성분×작물) 허용량을 하나도 해석하지 못함")
        return CollectResult(http_status=200, records_received=stored, records_valid=stored,
                             data_date=date, warnings=warnings[:5],
                             content_hash=sha(f"{date}:{stored}"),
                             schema_hash=sha("DIV8/TABLE/TR/TD"))
