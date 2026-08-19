"""핵심 로직 자체점검: python test_monitor.py  (프레임워크 없음, 네트워크 없음)"""
from src.collectors.japan import UNIFORM_LIMIT, _match_id, parse_detail
from src.collectors.canada import effective_date, parse_csv
from src.collectors.hongkong import parse_options, parse_report
from src.collectors.taiwan import applies_to, build_classes
from src.collectors.usa import build_group_index, parse_tolerances, resolve
from src.compare import commodity_mapped, guideline_verdict
from src.models import MrlKind, RegStatus, Severity
from src.normalize import parse_scalar
from src.compare import dday
from src.masters import member_label
from src.report import _clip, _rows_html, _titled, _verdict, _why_html, guideline_rows

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


CFR_GROUPS = """<DIV8 N="180.41" TYPE="SECTION"><HEAD>&#xA7; 180.41 Crop group tables.</HEAD>
<EXTRACT><HD1>Crop Group 11-10: Pome Fruit Group&#x2014;Commodities</HD1>
<FP-1>Apple, <I>Malus domestica</I> Borkh.</FP-1>
<FP-1>Pear, <I>Pyrus communis</I> L.</FP-1>
<FP-1>Pear, Asian, <I>Pyrus pyrifolia</I> (Burm. f.) Nakai</FP-1></EXTRACT>
<EXTRACT><HD1>Crop Group 13-07G: Low Growing Berry Subgroup&#x2014;Commodities</HD1>
<FP-1>Strawberry, <I>Fragaria</I> spp.</FP-1>
<FP-1>Cranberry, <I>Vaccinium macrocarpon</I> Aiton</FP-1></EXTRACT></DIV8>"""

CFR_SECTION = """<TABLE><TR><TD>Apple, wet pomace</TD><TD>3.0</TD></TR>
<TR><TD>Fruit, pome, group 11-10</TD><TD>0.60</TD></TR>
<TR><TD>Berry, low growing subgroups 13-07G, except cranberry</TD><TD>0.90</TD></TR>
<TR><TD>Pear, Asian <sup>1</sup></TD><TD>0.07</TD></TR></TABLE>"""


def test_usa_group_index():
    g = build_group_index(CFR_GROUPS)
    assert g["11-10"] == {"apple", "pear", "pear, asian"}   # 학명·저자명은 떨어져 나간다
    assert "pear, asian" in g["11-10"]             # 아시아배가 'pear' 로 뭉개지지 않는다
    assert "strawberry" in g["13-07G"]


def test_usa_resolution():
    rows = parse_tolerances(CFR_SECTION)
    g = build_group_index(CFR_GROUPS)
    assert len(rows) == 4
    assert ("Pear, Asian", "0.07") in rows         # 각주 표식 <sup>1</sup> 은 제거된다

    # 사과박(가공품)을 신선 사과로 쓰면 안 된다 — 작물그룹 행을 써야 한다
    assert resolve(rows, "Apple", g) == ("Fruit, pome, group 11-10", "0.60")
    assert resolve(rows, "Pear", g) == ("Fruit, pome, group 11-10", "0.60")
    # 한국 배 = 아시아배: 개별 등재가 있으면 그것을 쓴다
    assert resolve(rows, "Pear, Asian", g) == ("Pear, Asian", "0.07")
    # except 로 제외된 작물은 그 행을 쓰지 않는다
    assert resolve(rows, "Strawberry", g)[1] == "0.90"   # 'subgroups'(복수) 표기도 인식
    assert resolve(rows, "Cranberry", g) is None
    assert resolve(rows, "Banana", g) is None       # 어느 그룹에도 없으면 값 없음

    # 개별 품목 기준이 있으면 그룹보다 우선
    direct = rows + [("Apple", "0.5")]
    assert resolve(direct, "Apple", g) == ("Apple", "0.5")

    # 같은 작물의 표기가 그룹 세대별로 다르면 여러 표기를 준다
    g2 = dict(g, **{"11": {"apple", "pear, oriental"}})
    assert resolve([("Fruit, pome, group 11", "0.2")],
                   ["Pear, Asian", "Pear, oriental"], g2) == ("Fruit, pome, group 11", "0.2")


TW_CLASSES = [
    {"類別": "包葉菜類",
     "農作物類農產品": "十字花科包葉菜【甘藍(含球莖甘藍、抱子甘藍)、花椰菜、結球白菜、青花菜】、結球萵苣、朝鮮薊等。"},
    {"類別": "小漿果類", "農作物類農產品": "葡萄、草莓、蔓越莓、藍莓、覆盆子等。"},
    {"類別": "梨果類", "農作物類農產品": "蘋果、梨、桃(含油桃)、柿子等。"},
]


def test_taiwan_classes():
    c = build_classes(TW_CLASSES)
    assert "甘藍" in c["包葉菜類"] and "結球白菜" in c["包葉菜類"]
    # 【】로 묶인 소분류도 따로 색인된다 — 제외구가 소분류명으로 오기 때문
    assert c["十字花科包葉菜"] == {"甘藍", "花椰菜", "結球白菜", "青花菜"}
    assert "柿子" in c["梨果類"]        # 괄호 안 '、' 때문에 목록이 깨지지 않는다


def test_taiwan_exclusions():
    c = build_classes(TW_CLASSES)
    # 배추·양배추는 십자화과 → '十字花科包葉菜類除外' 행을 쓰면 안 된다
    row = "其他包葉菜類(十字花科包葉菜類、結球萵苣除外)"
    assert not applies_to(row, "甘藍", c)
    assert not applies_to(row, "結球白菜", c)
    assert applies_to(row, "朝鮮薊", c)          # 십자화과가 아니므로 적용된다

    # 작물명으로 제외한 경우
    berry = "其他小漿果類(藍莓、覆盆子除外)"
    assert applies_to(berry, "草莓", c) and applies_to(berry, "葡萄", c)
    assert not applies_to(berry, "藍莓", c)

    assert applies_to("梨果類", "蘋果", c)        # 류 전체 행
    assert not applies_to("梨果類", "草莓", c)
    # 정체를 모르는 제외 토큰이면 보수적으로 적용하지 않는다
    assert not applies_to("其他小漿果類(듣도보도못한것除外)", "草莓", c)
    assert applies_to("其他梨果類(柿子除外)", "蘋果", c)   # 별칭(柿↔柿子)
    assert not applies_to("其他梨果類(柿子除外)", "柿", c)


def test_indonesia_manual_file(tmp=None):
    """수동 입력 파일이 없으면 '미확인'으로 남아야 한다 — 없는 걸 있는 척하지 않는다."""
    import src.collectors.indonesia as idn
    from src.config import BASE_DIR

    real = idn.INDONESIA_FILE
    missing = BASE_DIR / "data" / "manual" / "__no_such_file__.csv"
    try:
        idn.INDONESIA_FILE = missing
        assert idn.read_rows() == []
        assert idn.known_commodities() == set()
    finally:
        idn.INDONESIA_FILE = real

    sample = BASE_DIR / "data" / "manual" / "indonesia_mrl.csv.example"
    if sample.exists():                      # 템플릿이 실제로 읽히는지도 확인
        try:
            idn.INDONESIA_FILE = sample
            rows = idn.read_rows()
            assert rows and idn.REQUIRED_COLUMNS <= set(rows[0])
            assert "사과" in idn.known_commodities()
        finally:
            idn.INDONESIA_FILE = real


HK_LIST = """<TR><TD title="Pear" ID='grpFP 0230'><a href="javascript:tosubmit('FP 0230'); ">Pear</a></TD></TR>
<TR><TD title="Peach, dried" ID='grpDF 0247'><a href="javascript:tosubmit('DF 0247'); ">Peach, dried</a></TD></TR>
<TR><TD title="Peach" ID='grpFS 0247'><a href="javascript:tosubmit('FS 0247'); ">Peach</a></TD></TR>"""

HK_REPORT = """<table>
<tr><td>Part 1/2 of the Schedule</td><td>Item</td><td>Pesticide</td><td>Residue definition</td>
    <td>Description of food</td><td>MRL/EMRL (mg/kg)</td></tr>
<tr><td>1</td><td>7.8</td><td>Abamectin</td><td>Sum of avermectin B1a and B1b</td>
    <td>Pear</td><td>0.02</td></tr>
<tr><td>1 record was found.</td></tr></table>"""


def test_hongkong_parsers():
    opts = parse_options(HK_LIST)
    # 식품 id 는 Codex 품목코드이며 'Peach' 와 'Peach, dried' 는 다른 품목이다
    assert opts["Pear"] == "FP 0230"
    assert opts["Peach"] == "FS 0247" and opts["Peach, dried"] == "DF 0247"

    rows = parse_report(HK_REPORT)
    assert rows == [("Pear", "0.02")]          # 머리글·안내문은 걸러진다
    assert parse_report("<table><tr><td>0 record was found.</td></tr></table>") == []


CA_CSV = ('Chemical Common Name,Food Commodity,MRL Value (ppm),Comments,Established Via\n'
          'Abamectin,Asian pears,0.02,,"MRL Database (26 April 2026) consulted via PMRL2026-02"\n'
          'Abamectin,Pears,0.03,,Canada Gazette II Prior to 16 June 2008\n')


def test_canada_csv():
    rows = parse_csv(CA_CSV)
    assert len(rows) == 2
    # 아시아배와 일반 배는 값이 다르다 — 한국 배는 아시아배를 먼저 본다
    assert rows[0]["Food Commodity"] == "Asian pears" and rows[0]["MRL Value (ppm)"] == "0.02"
    assert effective_date(rows[0]["Established Via"]) == "26 April 2026"
    assert effective_date(rows[1]["Established Via"]) == "16 June 2008"
    assert effective_date("") is None


def test_eping_member_country_map():
    """지침 국가명 ↔ ePing 회원국 표기가 실제로 이어져야 통보문을 대상국에 붙일 수 있다."""
    from src.compare import COUNTRY_SOURCE, EPING_MEMBER_COUNTRY
    # 값 대조/감시 중인 국가는 모두 매핑이 있어야 한다
    for country in COUNTRY_SOURCE:
        assert country in EPING_MEMBER_COUNTRY, country
    assert EPING_MEMBER_COUNTRY["중국"] == "China"
    assert EPING_MEMBER_COUNTRY["대만"] == "Chinese Taipei"   # ePing 은 'Taiwan' 을 쓰지 않는다


def test_standard_watch():
    """값을 못 읽는 기준이라도 판이 바뀌면 잡아내야 한다 — 그게 감시의 전부다."""
    import sqlite3
    from src import db
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)

    kw = dict(source="China", code="GB 2763-2021", published="2021-03-03",
              effective="2021-09-03", revision=None)
    assert db.record_standard(conn, **kw) is None      # 최초 등록은 개정이 아니다
    assert db.record_standard(conn, **kw) is None      # 그대로면 조용하다

    changed = db.record_standard(conn, **{**kw, "effective": "2027-01-01"})
    assert changed and "2021-09-03" in changed and "2027-01-01" in changed

    # 판 문자열만 바뀌어도(호주 컴필레이션 번호) 개정으로 잡는다
    au = dict(source="Australia", code="Schedule 20", published="2026-08-04",
              effective="2026-07-16", revision="compilation 91")
    db.record_standard(conn, **au)
    assert db.record_standard(conn, **{**au, "revision": "compilation 92"})


def test_clip():
    long = "Maximum levels of 3-monochloropropanediol (3-MCPD), 3-MCPD fatty acid esters and glycidyl"
    s = _clip(long, 56)
    assert s.endswith("…") and len(s) <= 57
    assert not s[:-1].endswith(" ")               # 잘린 끝에 공백/구두점을 남기지 않는다
    assert long.startswith(s[:-1])                # 원문 앞부분 그대로
    assert _clip("짧은 제목", 56) == "짧은 제목"    # 짧으면 …를 붙이지 않는다
    assert _clip(None) == ""
    assert _clip("A" * 80, 20).endswith("…")      # 공백 없는 긴 단어도 잘린다

    h = _titled(long, "https://example.org/n")
    assert "…" in h and "example.org" in h
    assert long in h                              # 전체 제목은 title 속성에 남는다


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
