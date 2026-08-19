"""운영보고서 + 대시보드 생성 (§24·§25·§35·§36).

두 축을 분리해서 보여준다: (A) 규정 현황  (B) 데이터 수집(시스템) 현황.
최신성 미확인은 '이상 없음'으로 표시하지 않는다.
"""
from __future__ import annotations

import html
from datetime import date

from . import db
from .config import OUT_DIR, REPORT_TITLE, SOURCES
from .masters import COMMODITIES, PESTICIDES

# 규정 상태 → 3분류 (§35)
REG_OK = {"MATCH", "RDA_STRICTER", "NO_FOREIGN_STANDARD"}
REG_REVIEW = {"REVIEW_REQUIRED", "AMBIGUOUS", "UNMAPPED"}
REG_FAIL = {"RDA_HIGHER", "FOREIGN_CHANGED", "REGISTRATION_CHANGED", "USAGE_CHANGED", "TARGET_CHANGED"}
# 시스템 상태 → 3분류
SYS_OK = {"HEALTHY"}
SYS_WARN = {"WARNING", "STALE", "AGING"}
SYS_FAIL = {"FAILED", "PARSER_ERROR", "SOURCE_UNAVAILABLE", "AUTH_ERROR", "SCHEMA_CHANGED", "UNKNOWN"}

DOT = {"ok": "🟢", "warn": "🟡", "fail": "🔴"}


def _sys_bucket(status: str) -> str:
    if status in SYS_OK:
        return "ok"
    if status in SYS_WARN:
        return "warn"
    return "fail"


def _reg_bucket(status: str) -> str:
    if status in REG_OK:
        return "ok"
    if status in REG_REVIEW:
        return "warn"
    return "fail"


def gather(conn) -> dict:
    health = [dict(r) for r in conn.execute("SELECT * FROM source_health").fetchall()]
    comps = [dict(r) for r in conn.execute(
        "SELECT * FROM comparison_results ORDER BY severity DESC").fetchall()]
    alerts = [dict(r) for r in conn.execute(
        "SELECT * FROM alerts WHERE acknowledged=0 ORDER BY id DESC LIMIT 100").fetchall()]
    changes = [dict(r) for r in conn.execute(
        "SELECT * FROM change_events ORDER BY id DESC LIMIT 50").fetchall()]
    sps = [dict(r) for r in conn.execute(
        "SELECT * FROM sps_notifications ORDER BY distribution_date DESC LIMIT 30").fetchall()]
    # 지침에 없는 (성분×작물×국가)도 현행 기준은 보여준다 — 비교표 빈칸 대신 회색 참고값
    live = {(r["source"], r["pesticide_en"], r["commodity_ko"]): r["mrl_display"]
            for r in conn.execute("SELECT source,pesticide_en,commodity_ko,mrl_display FROM foreign_mrls")}

    reg_counts = {"ok": 0, "warn": 0, "fail": 0}
    for c in comps:
        reg_counts[_reg_bucket(c["status"])] += 1
    sys_counts = {"ok": 0, "warn": 0, "fail": 0}
    for h in health:
        sys_counts[_sys_bucket(h["status"] or "UNKNOWN")] += 1
    # 아직 수집 시도 안 한 소스도 집계
    for name in SOURCES:
        if not any(h["source"] == name for h in health):
            sys_counts["fail"] += 1

    sev_order = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0}
    item_order = {"REGISTRATION": 3, "GUIDELINE": 2, "EXPORT_MARGIN": 1}
    comps.sort(key=lambda c: (item_order.get(c["item"], 0), sev_order.get(c["severity"], 0)),
               reverse=True)

    # 담당자 조치사항 (의사결정)
    actions = {
        "update_guideline": [c for c in comps if c["item"] == "GUIDELINE" and c["status"] == "FOREIGN_CHANGED"],
        "no_export": [c for c in comps if c["item"] == "REGISTRATION"],
        "stale": [c for c in comps if c["item"] == "GUIDELINE" and c["status"] == "REVIEW_REQUIRED"],
        "upcoming": [a for a in alerts if a["category"] == "UPCOMING"],
    }
    return {
        "date": date.today().isoformat(),
        "health": health, "comps": comps, "alerts": alerts,
        "changes": changes, "sps": sps,
        "live": live,
        "reg_counts": reg_counts, "sys_counts": sys_counts,
        "actions": actions,
        "reg_alerts": [a for a in alerts if a["category"] in ("REGULATION", "REGISTRATION")],
        "sys_alerts": [a for a in alerts if a["category"] == "SYSTEM"],
    }


def render_text(g: dict) -> str:
    """카카오/짧은 알림용 요약 텍스트 — 조치사항 중심."""
    a, sc = g["actions"], g["sys_counts"]
    lines = [
        f"[{REPORT_TITLE}] {g['date']}",
        f"🔴 지침갱신 {len(a['update_guideline'])} · 수출불가 {len(a['no_export'])} · "
        f"변경예고 {len(a['upcoming'])} · 최신성확인 {len(a['stale'])}",
        f"수집: 🟢{sc['ok']} 🟡{sc['warn']} 🔴{sc['fail']}",
    ]
    top = (a["no_export"] or a["update_guideline"])
    if top:
        c = top[0]
        lines.append(f"예: {c['source']} {c['commodity_ko']}/{c['pesticide_en']} — {(c['detail'] or '')[:60]}")
    elif not a["upcoming"] and not a["stale"]:
        lines.append("조치 필요사항 없음(최신 확인됨)")
    return "\n".join(lines)[:190]


COL_SOURCES = [("EU", "EU"), ("Japan", "일본")]


def _cell(c: dict | None, ref: str | None = None) -> str:
    """비교결과 1건 → 표 셀. 값이 바뀐 것만 '지침→현행'으로 두 값을 보여준다.

    지침이 그 나라를 대상으로 하지 않는 조합은 비교 대상이 아니므로,
    현행 기준만 회색 참고값으로 보여준다(판정 없음).
    """
    if c is None:
        return f"<td class='v nil'>{html.escape(ref)}</td>" if ref else "<td class=nil>·</td>"
    b = _reg_bucket(c["status"])
    cur = html.escape(c["foreign_mrl"] or "-")
    detail = html.escape(c["detail"] or "")
    if c["status"] == "FOREIGN_CHANGED" and c.get("published_mrl"):
        cur = f"<s>{html.escape(c['published_mrl'])}</s> {cur}"
    elif c["status"] != "MATCH":
        cur = cur or "?"
    warn = "" if c["data_confidence"] == "HIGH" else " ◦"
    return f'<td class="v {b}" title="{detail}">{cur}{warn}</td>'


def _matrix_html(comps: list[dict], live: dict) -> str:
    """작물 × 성분 행, 국내/EU/일본 열.

    지침에 실린 조합은 판정색으로, 지침 대상이 아닌 조합은 현행 기준만 회색 참고값으로.
    양쪽 다 없는 조합은 행을 만들지 않는다.
    """
    judged = {(c["commodity_ko"], c["pesticide_ko"], c["source"]): c
              for c in comps if c["item"] == "GUIDELINE"}
    korea = {(c["commodity_ko"], c["pesticide_ko"]): c["korea_mrl"]
             for c in comps if c["item"] == "GUIDELINE"}

    body = []
    for commodity in COMMODITIES:
        first = True
        for pest, pm in PESTICIDES.items():
            en = pm["english"]
            cells = [(judged.get((commodity, pest, s)), live.get((s, en, commodity)))
                     for s, _lbl in COL_SOURCES]
            if not any(c or ref for c, ref in cells):
                continue
            body.append(f"<tr><td class=grp>{html.escape(commodity) if first else ''}</td>"
                        f"<td>{html.escape(pest)}<br><small>{html.escape(en)}</small></td>"
                        f"<td class=v>{html.escape(korea.get((commodity, pest)) or '-')}</td>"
                        + "".join(_cell(c, ref) for c, ref in cells) + "</tr>")
            first = False
    if not body:
        return "<p><small>표시할 (작물×성분) 조합이 없습니다.</small></p>"
    return ("<table class=mx><tr><th>작물</th><th>성분</th><th>국내지침</th>"
            + "".join(f"<th>{lbl}</th>" for _s, lbl in COL_SOURCES) + "</tr>"
            + "".join(body) + "</table>")


def _todo_html(g: dict) -> str:
    """조치가 필요한 건만 한 줄씩. 없으면 한 줄로 끝낸다."""
    a = g["actions"]
    lines = []
    for c in a["no_export"]:
        lines.append(f"<li class=fail>⛔ <b>{html.escape(c['source'])} {html.escape(c['commodity_ko'])}"
                     f"/{html.escape(c['pesticide_ko'])}</b> 수출용 사용 불가 — "
                     f"<small>{html.escape(c['detail'] or '')}</small></li>")
    for c in a["update_guideline"]:
        lines.append(f"<li class=fail>🔴 <b>{html.escape(c['source'])} {html.escape(c['commodity_ko'])}"
                     f"/{html.escape(c['pesticide_ko'])}</b> 지침 갱신 — "
                     f"<small>{html.escape(c['detail'] or '')}</small></li>")
    for c in a["stale"]:
        lines.append(f"<li class=warn>⚠ <b>{html.escape(c['source'])} {html.escape(c['commodity_ko'])}"
                     f"/{html.escape(c['pesticide_ko'])}</b> 최신성 확인 — "
                     f"<small>{html.escape(c['detail'] or '')}</small></li>")
    if not lines:
        return "<p class=none>✅ 지금 조치할 항목 없음 (모든 소스 최신 확인됨)</p>"
    return f"<ul class=todo>{''.join(lines)}</ul>"


def _chips_html(health: list[dict]) -> str:
    seen = {h["source"]: h for h in health}
    out = []
    for name in SOURCES:
        h = seen.get(name)
        st = (h["status"] if h else "UNKNOWN") or "UNKNOWN"
        msg = (h["status_message"] if h else "") or ""
        when = (h["last_success_at"] if h and h["last_success_at"] else "없음")[:16]
        out.append(f'<span class="chip {_sys_bucket(st)}" title="{html.escape(st)} · 마지막 정상수집 '
                   f'{html.escape(when)} {html.escape(msg[:120])}">{DOT[_sys_bucket(st)]} {name}</span>')
    return "".join(out)


def _fold(title: str, n: int, body: str) -> str:
    return f"<details><summary>{title} <b>{n}</b></summary>{body}</details>"


def render_html(g: dict) -> str:
    a = g["actions"]
    todo_n = len(a["no_export"]) + len(a["update_guideline"]) + len(a["stale"])
    upcoming = "".join(
        f"<li>{html.escape(x['title'])}<br><small>{html.escape((x['body'] or '')[:180])}</small></li>"
        for x in a["upcoming"]) or "<li>없음</li>"
    alerts_html = "".join(
        f"<li><b>[{html.escape(x['severity'])}]</b> {html.escape(x['title'])}"
        f"<br><small>{html.escape((x['body'] or '')[:200])}</small></li>"
        for x in g["alerts"][:30]) or "<li>없음</li>"
    sps_html = "".join(
        f"<li><small>{html.escape((s['distribution_date'] or '')[:10])} · {html.escape(s['member'] or '')}</small> "
        f"{html.escape((s['title'] or '')[:120])}</li>"
        for s in g["sps"][:15]) or "<li>없음</li>"

    return f"""<!doctype html><html lang=ko><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>{REPORT_TITLE} {g['date']}</title>
<style>
 :root{{--line:#e3e6ea;--ok:#0a7d33;--warn:#a86500;--fail:#c0281f}}
 *{{box-sizing:border-box}}
 body{{font-family:-apple-system,'Noto Sans KR','Malgun Gothic',sans-serif;margin:0;
      background:#f6f7f9;color:#1a1a1a;font-size:14px;line-height:1.45}}
 .wrap{{max-width:920px;margin:0 auto;padding:14px}}
 h1{{font-size:17px;margin:0 0 8px}} h1 small{{font-weight:400;color:#666}}
 h2{{font-size:14px;margin:20px 0 6px;color:#33414f}}
 .strip{{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:12px}}
 .chip{{background:#fff;border:1px solid var(--line);border-radius:99px;padding:2px 9px;font-size:12.5px}}
 .chip.ok{{border-color:#bfe3c9}} .chip.warn{{border-color:#f0d9a8}} .chip.fail{{border-color:#f3bdb8;background:#fff5f4}}
 .count{{font-weight:700;border-radius:6px;padding:2px 9px;font-size:12.5px;border:1px solid var(--line);background:#fff}}
 .count.hit{{background:#fdecea;border-color:#f3bdb8;color:var(--fail)}}
 ul.todo{{list-style:none;margin:0;padding:0;background:#fff;border:1px solid var(--line);border-radius:8px}}
 ul.todo li{{padding:7px 10px;border-bottom:1px solid var(--line)}}
 ul.todo li:last-child{{border-bottom:0}}
 li.fail{{border-left:3px solid var(--fail)}} li.warn{{border-left:3px solid var(--warn)}}
 .none{{background:#fff;border:1px solid var(--line);border-radius:8px;padding:9px 10px;margin:0;color:var(--ok)}}
 table.mx{{width:100%;border-collapse:collapse;background:#fff;font-size:13px}}
 table.mx th,table.mx td{{border:1px solid var(--line);padding:4px 7px;text-align:left}}
 table.mx th{{background:#eef1f4;font-weight:600;font-size:12.5px}}
 td.v{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
 td.grp{{font-weight:700;background:#fafbfc}} td.nil{{text-align:center;color:#bbb}}
 td.ok{{color:var(--ok)}} td.warn{{background:#fff8e6;color:var(--warn)}}
 td.fail{{background:#fdecea;color:var(--fail);font-weight:700}}
 td.v s{{color:#999;font-weight:400}}
 details{{background:#fff;border:1px solid var(--line);border-radius:8px;margin:6px 0;padding:6px 10px}}
 summary{{cursor:pointer;font-size:13px;color:#33414f}}
 details ul{{margin:6px 0 2px;padding-left:18px;font-size:12.5px}}
 small{{color:#667}}
 .foot{{color:#889;font-size:11.5px;margin-top:14px}}
</style></head><body><div class=wrap>
<h1>📋 {REPORT_TITLE} <small>{g['date']}</small></h1>
<div class=strip>
 <span class="count {'hit' if todo_n else ''}">조치 {todo_n}</span>
 <span class=count>예고 {len(a['upcoming'])}</span>
 {_chips_html(g['health'])}
</div>

<h2>지금 조치할 것</h2>
{_todo_html(g)}

<h2>기준 비교 <small>(mg/kg · <s>취소선</s>=지침 배포값, 옆이 현행 · 회색=지침 대상국 아님(참고) · ◦=최신성 미확인)</small></h2>
{_matrix_html(g['comps'], g['live'])}

{_fold('🕒 변경 예고 (WTO/SPS)', len(a['upcoming']), f'<ul>{upcoming}</ul>')}
{_fold('🔔 알림', len(g['alerts']), f'<ul>{alerts_html}</ul>')}
{_fold('📄 SPS 통보문', len(g['sps']), f'<ul>{sps_html}</ul>')}
<p class=foot>"변경 없음"이 아니라 "최신 정보를 정상 확인했고 그 결과 변경 없음"을 뜻합니다.
 수집 실패 소스의 값은 조치목록에 '최신성 확인'으로 올라옵니다. · 생성 {db.now_iso()}</p>
</div></body></html>"""


def build(conn) -> dict:
    g = gather(conn)
    html_doc = render_html(g)
    text = render_text(g)
    dash = OUT_DIR / "dashboard.html"
    dash.write_text(html_doc, encoding="utf-8")
    dated = OUT_DIR / f"report_{g['date']}.html"
    dated.write_text(html_doc, encoding="utf-8")
    (OUT_DIR / "report_latest.txt").write_text(text, encoding="utf-8")
    return {"summary": g, "html": html_doc, "text": text,
            "dashboard_path": str(dash), "report_path": str(dated)}
