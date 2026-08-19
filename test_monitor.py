"""핵심 로직 자체점검: python test_monitor.py  (프레임워크 없음, 네트워크 없음)"""
from src.collectors.japan import UNIFORM_LIMIT, _match_id, parse_detail
from src.compare import guideline_verdict
from src.models import MrlKind, RegStatus, Severity
from src.normalize import parse_scalar
from src.report import _cell, _matrix_html

FIXTURE = """
<table><thead><tr><th>Food Type</th><th>MRLs(ppm)</th><th>Basis</th><th>Note</th>
<th>MRLs(ppm)（Time limit）</th></tr></thead><tbody>
<tr data-href="/x"><td>Apple</td><td>0.5</td><td>Ab2010</td><td></td><td></td></tr>
<tr data-href="/x"><td>Strawberry</td><td>1</td><td>Ab2015</td><td></td><td>2 (2026.10.06)</td></tr>
</tbody></table>"""


def test_japan_parse():
    t = parse_detail(FIXTURE)
    assert t["Apple"] == ("0.5", ""), t
    assert t["Strawberry"] == ("1", "2 (2026.10.06)"), t
    assert "Grape" not in t                    # 표에 없는 작물 → 일률기준 경로로 간다
    assert UNIFORM_LIMIT == 0.01


def test_japan_name_match():
    idx = {"ABAMECTIN": "1", "ALDICARB AND ALDOXYCARB": "2", "ACETAMIPRID": "3"}
    assert _match_id(idx, "Abamectin") == "1"
    assert _match_id(idx, "Aldoxycarb") == "2"      # 합산 성분 표기 안에서 찾기
    assert _match_id(idx, "Nosuchthing") is None


def test_verdict():
    same = guideline_verdict(parse_scalar("2"), parse_scalar("2"))
    assert same[0] is RegStatus.MATCH
    stricter = guideline_verdict(parse_scalar("2"), parse_scalar("1"))
    assert stricter[0] is RegStatus.FOREIGN_CHANGED and stricter[1] is Severity.CRITICAL
    looser = guideline_verdict(parse_scalar("1"), parse_scalar("2"))
    assert looser[1] is Severity.HIGH              # 완화는 위반 위험 아님 → CRITICAL 아님
    gone = guideline_verdict(parse_scalar("2"), parse_scalar("-"))
    assert gone[0] is RegStatus.REVIEW_REQUIRED
    assert parse_scalar("0.01(일률기준)").kind is MrlKind.NORMAL


def test_matrix_cells():
    changed = {"status": "FOREIGN_CHANGED", "published_mrl": "2", "foreign_mrl": "1",
               "detail": "지침 2 → 현행 1", "data_confidence": "HIGH"}
    assert "<s>2</s> 1" in _cell(changed)
    assert _cell(None) == "<td class=nil>·</td>"
    assert ">0.5<" in _cell(None, "0.5")            # 지침 대상국 아님 → 회색 참고값
    assert "◦" in _cell({**changed, "data_confidence": "LOW"})   # 최신성 미확인 표시

    comps = [{"item": "GUIDELINE", "commodity_ko": "딸기", "pesticide_ko": "아바멕틴",
              "pesticide_en": "Abamectin", "source": "Japan", "korea_mrl": "0.1",
              "foreign_mrl": "0.2", "status": "MATCH", "detail": "", "data_confidence": "HIGH"}]
    h = _matrix_html(comps, {("EU", "Abamectin", "딸기"): "0.08"})
    assert "아바멕틴" in h and "0.2" in h and "0.08" in h
    assert "포도" not in h                          # 값 없는 작물 행은 만들지 않는다


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
