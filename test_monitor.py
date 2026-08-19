"""핵심 로직 자체점검: python test_monitor.py  (프레임워크 없음, 네트워크 없음)"""
from src.collectors.japan import UNIFORM_LIMIT, _match_id, parse_detail
from src.compare import commodity_mapped, guideline_verdict
from src.models import MrlKind, RegStatus, Severity
from src.normalize import parse_scalar
from src.compare import dday
from src.masters import member_label
from src.report import _rows_html, _verdict, _why_html, guideline_rows

FIXTURE = """
<table><thead><tr><th>Food Type</th><th>MRLs(ppm)</th><th>Basis</th><th>Note</th>
<th>MRLs(ppm)（Time limit）</th></tr></thead><tbody>
<tr data-href="/x"><td>Apple</td><td>0.5</td><td>Ab2010</td><td></td><td></td></tr>
<tr data-href="/x"><td>Strawberry</td><td>1</td><td>Ab2015</td><td></td><td>2 (2026.10.06)</td></tr>
</tbody></table>"""


def test_japan_parse():
    t = parse_detail(FIXTURE)
    assert t["Apple"] == ("0.5", "", "Ab2010"), t
    assert t["Strawberry"] == ("1", "2 (2026.10.06)", "Ab2015"), t   # 본기준·경과조치·설정근거
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


def test_dday():
    assert dday(30) == "D-30" and dday(0) == "D-DAY" and dday(-5) == "D+5" and dday(None) == "D-?"


def test_member_label():
    assert member_label("United Kingdom") == "🇬🇧 UK"
    assert member_label("United States of America") == "🇺🇸 USA"
    assert member_label("Atlantis") == "Atlantis"        # 모르는 회원국은 지어내지 않는다


def test_rows_show_published_vs_current():
    changed = {"item": "GUIDELINE", "commodity_ko": "딸기", "pesticide_ko": "스피네토람",
               "pesticide_en": "Spinetoram", "source": "Japan", "korea_mrl": "0.2",
               "published_mrl": "2", "foreign_mrl": "1", "status": "FOREIGN_CHANGED",
               "severity": "CRITICAL", "detail": "지침 2 → 현행 1", "data_confidence": "HIGH",
               "basis": "Ab2025", "changed_at": "2026-08-19 최초 확인",
               "source_url": "https://db.ffcr.or.jp/x", "evidence": None}
    h = _rows_html([changed])
    assert ">2<" in h and ">1<" in h                     # 지침값과 현행값이 함께 보인다
    assert "Ab2025" in h and "db.ffcr.or.jp" in h        # 근거와 원문 링크
    assert "2026-08-19" in h                             # 시점
    assert _verdict(changed)[0] == "🔴 다름"
    assert "엄격" in _verdict(changed)[1]

    assert "근거자료 없음" in _why_html({"basis": None, "changed_at": None, "source_url": None})
    # 국내 MRL 비교(EXPORT_MARGIN)와 일치 건은 본표에서 빠진다 — 볼 이유가 없다
    diff, same = guideline_rows([changed, {**changed, "item": "EXPORT_MARGIN"},
                                 {**changed, "status": "MATCH"}])
    assert len(diff) == 1 and len(same) == 1
    assert "일치합니다" in _rows_html([])


def test_coverage_mapping():
    assert commodity_mapped("Japan", "양배추")          # FFCR 식품명 확인됨
    assert not commodity_mapped("Japan", "고추")        # 대응 항목 미확정 → 대조 대상 아님
    assert not commodity_mapped("EU", "양배추")         # EU product_id 미확인
    assert commodity_mapped("EU", "배")
    assert not commodity_mapped("Japan", "없는작목")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
