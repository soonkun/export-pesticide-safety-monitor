"""Taiwan (TFDA) collector — 農藥殘留容許量標準, 정부 오픈데이터 API.

대만 위생복리부 식품약물관리서(TFDA)가 잔류농약 허용기준을 오픈데이터로 공개한다(무키).
엔드포인트는 추측이 아니라 TFDA 가 게시한 OpenAPI 명세에서 확인했다:
  swagger-config → /data/dataset/oas/classification/<食品> → paths['/opendata/export/13/json']
서버 base 는 https://data.fda.gov.tw/data 이며 **Accept: application/json 헤더가 없으면
HTML 페이지가 돌아온다**(실측).

레코드: {國際普通名稱(영문 일반명), 普通名稱, 作物類別, 容許量ppm, 備註}

作物類別 는 세 가지 형태다:
  · 개별 작물          '蘋果'(사과), '桃(油桃除外)'(복숭아, 넥타린 제외)
  · 류 전체            '梨果類'
  · 류에서 일부 제외    '其他小漿果類(藍莓、覆盆子除外)'
어느 작물이 어느 류에 속하는지는 **같은 기관이 공개하는 農作物類農產品之分類表(export/16)**
에 규정돼 있으므로 추측 없이 색인해 해석한다. 예: 小漿果類 = 葡萄、草莓、…、藍莓、…

채택 규칙(§30 — 확실할 때만 값을 쓴다):
  1) 作物類別 가 대상 작물과 정확히 일치하면 채택(개별 등재가 그룹보다 우선).
  2) 아니면 대상 작물이 속한 류의 그룹 행 중 제외되지 않은 것을 채택.
  3) 후보의 값이 서로 다르면 채택하지 않고 경고만 남긴다.
"""
from __future__ import annotations

import re
from collections import defaultdict

from .. import db
from ..config import TAIWAN_CLASS_URL, TAIWAN_MRL_URL, TAIWAN_SOURCE_PAGE
from ..http import ParserError, SourceUnavailable
from ..masters import COMMODITIES, PESTICIDES
from ..normalize import parse_scalar
from .base import BaseCollector, CollectResult, sha

EXPECTED_FIELDS = {"國際普通名稱", "作物類別", "容許量ppm"}

# 분류표는 '柿子', 허용량표는 '柿' 로 쓴다. 표기 차이는 명시적으로만 잇는다(유사어 추측 금지).
CLASS_ALIAS = {"柿": "柿子"}

_PARENS = re.compile(r"\([^()]*\)|（[^（）]*）")
_OTHER = re.compile(r"^其他(?P<cat>[^()（）]+類)\s*(?:[(（](?P<exc>.*?)除外[)）])?$")
_WHOLE = re.compile(r"^(?P<cat>[^()（）]+類)$")


def _strip_parens(x: str) -> str:
    """중첩 괄호까지 제거. 괄호 안의 '、' 때문에 목록 분리가 깨지는 것을 막는다."""
    prev = None
    while prev != x:
        prev, x = x, _PARENS.sub("", x)
    return x


def _norm(x: str) -> str:
    return _strip_parens(re.sub(r"[【】]", "", x)).strip().rstrip("等。 ").strip()


_SUBGROUP = re.compile(r"(?P<name>[^、,【】()（）]+)【(?P<members>[^】]*)】")


def build_classes(rows: list[dict]) -> dict[str, set[str]]:
    """農作物類農產品之分類表 → {類別/소분류: {구성 작물}}.

    본문에는 '十字花科包葉菜【甘藍、花椰菜、結球白菜、…】' 처럼 【】로 묶인 **소분류**가 있다.
    허용량표의 제외구가 작물명이 아니라 이 소분류명으로 오는 경우가 있어
    ('其他包葉菜類(十字花科包葉菜類、結球萵苣除外)') 소분류도 함께 색인해야 한다.
    이걸 놓치면 배추·양배추처럼 **제외된 작물에 남의 기준을 붙이게 된다.**
    """
    out: dict[str, set[str]] = {}
    for r in rows:
        raw = r.get("農作物類農產品") or ""
        for sm in _SUBGROUP.finditer(raw):
            body = _strip_parens(sm.group("members"))
            members = {_norm(p) for p in re.split(r"[、,]", body) if _norm(p)}
            if members:
                out[_norm(sm.group("name"))] = members
        body = re.sub(r"[【】]", "、", raw)
        members = {_norm(p) for p in re.split(r"[、,]", _strip_parens(body)) if _norm(p)}
        # 괄호 안에 열거된 하위 작물도 그 류의 구성원이다
        #   '木莓(包括覆盆子、黑莓等)' → 覆盆子·黑莓,  '桃(含油桃)' → 油桃
        for inner in re.findall(r"[(（]([^()（）]*)[)）]", body):
            inner = re.sub(r"^(含|包括)", "", inner.strip())
            members |= {_norm(p) for p in re.split(r"[、,]", inner) if _norm(p)}
        members.discard("")
        if r.get("類別") and members:
            out[r["類別"].strip()] = members
    if not out:
        raise ParserError("TFDA 작물분류표 파싱 결과가 비어 있음")
    return out


def applies_to(category: str, crop: str, classes: dict[str, set[str]]) -> bool:
    """허용량표의 作物類別 가 대상 작물에 적용되는 그룹 행인가."""
    member = CLASS_ALIAS.get(_norm(crop), _norm(crop))
    m = _OTHER.match(category.strip()) or _WHOLE.match(category.strip())
    if not m:
        return False
    if member not in classes.get(m.group("cat"), set()):
        return False
    for token in re.split(r"[、,]", m.groupdict().get("exc") or ""):
        tok = CLASS_ALIAS.get(_norm(token), _norm(token))
        if not tok:
            continue
        if tok == member:
            return False
        group = classes.get(tok) or classes.get(tok.rstrip("類"))
        if group is not None:
            if member in group:
                return False                 # 제외구가 소분류명인 경우 (예: 十字花科包葉菜類)
            continue
        if tok not in classes.get(m.group("cat"), set()):
            # 정체를 모르는 제외 토큰 — 우리 작물이 여기 포함될 수도 있으므로 이 행은 쓰지 않는다
            return False
    return True


class TaiwanCollector(BaseCollector):
    name = "Taiwan"

    def collect(self, conn, s) -> CollectResult:
        try:
            r = s.get(TAIWAN_MRL_URL, headers={"Accept": "application/json"}, timeout=120)
        except Exception as e:
            raise SourceUnavailable(f"TFDA 오픈데이터 접속 실패: {e}")
        if r.status_code != 200:
            raise SourceUnavailable(f"TFDA HTTP {r.status_code}")
        try:
            rows = r.json()
        except ValueError:
            raise SourceUnavailable(
                "TFDA 응답이 JSON 이 아님 — Accept 헤더 누락 시 HTML 이 돌아온다")
        if not rows or not EXPECTED_FIELDS.issubset(rows[0].keys()):
            raise ParserError(f"TFDA 필드 구조 변경 의심: {sorted(rows[0].keys()) if rows else '빈 응답'}")

        # (성분, 작물류별) → {허용량}. 값이 엇갈리면 채택하지 않는다.
        index: dict[tuple[str, str], set[str]] = defaultdict(set)
        note: dict[tuple[str, str], str] = {}
        for row in rows:
            key = ((row.get("國際普通名稱") or "").strip().lower(), (row.get("作物類別") or "").strip())
            index[key].add((row.get("容許量ppm") or "").strip())
            note[key] = (row.get("備註") or "").strip()

        cr = s.get(TAIWAN_CLASS_URL, headers={"Accept": "application/json"}, timeout=60)
        try:
            classes = build_classes(cr.json())
        except ValueError:
            raise SourceUnavailable("TFDA 작물분류표 응답이 JSON 이 아님")

        # 성분별 (作物類別 → 허용량) 로 다시 묶어 그룹 행 탐색에 쓴다
        by_pest: dict[str, dict[str, str]] = defaultdict(dict)
        for (en_low, cat), vals in index.items():
            if len(vals) == 1:
                by_pest[en_low][cat] = next(iter(vals))

        stored = 0
        warnings: list[str] = []
        for pest_ko, pm in PESTICIDES.items():
            en = pm["english"]
            for commodity_ko, cm in COMMODITIES.items():
                crop = cm.get("taiwan_name")
                if not crop:
                    continue
                cats = by_pest.get(en.lower(), {})
                if crop in cats:                       # (1) 개별 등재 우선
                    category, value = crop, cats[crop]
                else:                                  # (2) 그룹 행
                    hits = {c: v for c, v in cats.items() if applies_to(c, crop, classes)}
                    if not hits:
                        continue
                    if len(set(hits.values())) > 1:    # (3) 값이 엇갈리면 미채택
                        warnings.append(f"{en}/{commodity_ko}: 그룹 기준 상충 {sorted(hits)}")
                        continue
                    category, value = sorted(hits)[0], next(iter(hits.values()))
                basis = f"農藥殘留容許量標準 — {category}"
                if note.get((en.lower(), category)):
                    basis += f" ({note[(en.lower(), category)]})"
                db.record_foreign_mrl(
                    conn, source=self.name, pesticide_en=en, commodity_ko=commodity_ko,
                    commodity_src=crop, mrl=parse_scalar(value),
                    source_url=TAIWAN_SOURCE_PAGE, basis=basis)
                stored += 1

        if not stored:
            raise ParserError("TFDA 자료에서 대상 (성분×작물) 허용량을 하나도 찾지 못함")
        return CollectResult(http_status=200, records_received=stored, records_valid=stored,
                             warnings=warnings[:5], content_hash=sha(str(len(rows))),
                             schema_hash=sha(",".join(sorted(EXPECTED_FIELDS))))
