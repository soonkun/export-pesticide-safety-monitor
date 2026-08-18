"""운영보고서 + 대시보드 생성 (§24·§25·§35·§36).

두 축을 분리해서 보여준다: (A) 규정 현황  (B) 데이터 수집(시스템) 현황.
최신성 미확인은 '이상 없음'으로 표시하지 않는다.
"""
from __future__ import annotations

import html
from datetime import date

from . import db
from .config import OUT_DIR, REPORT_TITLE, SOURCES

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
    comps.sort(key=lambda c: (sev_order.get(c["severity"], 0), c["status"]), reverse=True)

    return {
        "date": date.today().isoformat(),
        "health": health, "comps": comps, "alerts": alerts,
        "changes": changes, "sps": sps,
        "reg_counts": reg_counts, "sys_counts": sys_counts,
        "reg_alerts": [a for a in alerts if a["category"] == "REGULATION"],
        "sys_alerts": [a for a in alerts if a["category"] == "SYSTEM"],
    }


def render_text(g: dict) -> str:
    """카카오/짧은 알림용 요약 텍스트."""
    rc, sc = g["reg_counts"], g["sys_counts"]
    lines = [
        f"[{REPORT_TITLE}] {g['date']}",
        f"규정: 🟢{rc['ok']} 🟡{rc['warn']} 🔴{rc['fail']}",
        f"수집: 🟢{sc['ok']} 🟡{sc['warn']} 🔴{sc['fail']}",
    ]
    if g["reg_alerts"]:
        lines.append(f"규정알림 {len(g['reg_alerts'])}건 (예: {g['reg_alerts'][0]['title']})")
    if g["sys_alerts"]:
        lines.append(f"시스템알림 {len(g['sys_alerts'])}건 (예: {g['sys_alerts'][0]['title']})")
    if not g["reg_alerts"] and not g["sys_alerts"]:
        lines.append("신규 알림 없음")
    return "\n".join(lines)[:190]


def _rows_html(comps: list[dict]) -> str:
    out = []
    for c in comps:
        b = _reg_bucket(c["status"])
        conf = c["data_confidence"]
        conf_warn = "" if conf == "HIGH" else " style='color:#b30'"
        out.append(
            f"<tr><td>{DOT[b]}</td><td>{html.escape(c['source'])}</td>"
            f"<td>{html.escape(c['commodity_ko'])}</td><td>{html.escape(c['pesticide_ko'])}"
            f"<br><small>{html.escape(c['pesticide_en'])}</small></td>"
            f"<td>{html.escape(c['korea_mrl'] or '-')}</td>"
            f"<td>{html.escape(c['foreign_mrl'] or '-')}</td>"
            f"<td><b>{html.escape(c['status'])}</b><br><small>{html.escape(c['detail'] or '')}</small></td>"
            f"<td>{html.escape(c['severity'])}</td>"
            f"<td{conf_warn}>{html.escape(conf)}<br><small>{html.escape(c['source_status'] or '')}/"
            f"{html.escape(c['source_freshness'] or '')}</small></td>"
            f"<td><small>정상수집 {html.escape((c['last_success_at'] or '없음')[:16])}</small></td></tr>")
    return "\n".join(out)


def _health_html(health: list[dict]) -> str:
    seen = {h["source"]: h for h in health}
    out = []
    for name, meta in SOURCES.items():
        h = seen.get(name)
        status = (h["status"] if h else "UNKNOWN")
        b = _sys_bucket(status or "UNKNOWN")
        fresh = (h["freshness"] if h else "UNKNOWN")
        last_ok = (h["last_success_at"] if h and h["last_success_at"] else "없음")
        last_try = (h["latest_attempt_at"] if h and h["latest_attempt_at"] else "없음")
        recs = (h["number_of_records"] if h else 0)
        msg = (h["status_message"] if h and h["status_message"] else "")
        out.append(
            f"<tr><td>{DOT[b]}</td><td>{name}</td><td>{meta['country']}</td>"
            f"<td><b>{html.escape(status or '')}</b></td><td>{html.escape(fresh or '')}</td>"
            f"<td>{recs}</td><td><small>{html.escape(str(last_ok)[:16])}</small></td>"
            f"<td><small>{html.escape(str(last_try)[:16])}</small></td>"
            f"<td><small>{html.escape(msg)}</small></td></tr>")
    return "\n".join(out)


def render_html(g: dict) -> str:
    rc, sc = g["reg_counts"], g["sys_counts"]
    alerts_html = "".join(
        f"<li><b>[{html.escape(a['severity'])}]</b> {html.escape(a['category'])} — "
        f"{html.escape(a['title'])}<br><small>{html.escape((a['body'] or '')[:300])}</small></li>"
        for a in g["alerts"][:30]) or "<li>신규 알림 없음</li>"
    sps_html = "".join(
        f"<li><small>{html.escape((s['distribution_date'] or '')[:10])} · {html.escape(s['member'] or '')} · "
        f"{html.escape(s['document_symbol'] or '')}</small><br>{html.escape((s['title'] or '')[:160])}</li>"
        for s in g["sps"][:15]) or "<li>수집된 SPS 통보문 없음</li>"

    return f"""<!doctype html><html lang=ko><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>{REPORT_TITLE} {g['date']}</title>
<style>
 body{{font-family:-apple-system,'Malgun Gothic',sans-serif;margin:0;background:#f4f6f8;color:#1a1a1a}}
 .wrap{{max-width:1100px;margin:0 auto;padding:16px}}
 h1{{font-size:20px}} h2{{font-size:16px;margin-top:28px;border-left:4px solid #345;padding-left:8px}}
 .cards{{display:flex;gap:16px;flex-wrap:wrap}}
 .card{{flex:1;min-width:280px;background:#fff;border-radius:10px;padding:16px;box-shadow:0 1px 3px rgba(0,0,0,.1)}}
 .big{{font-size:15px;line-height:2}} .ok{{color:#0a0}} .warn{{color:#b80}} .fail{{color:#c00}}
 table{{width:100%;border-collapse:collapse;background:#fff;font-size:13px;overflow:hidden;border-radius:8px}}
 th,td{{border:1px solid #e3e6ea;padding:6px 8px;text-align:left;vertical-align:top}}
 th{{background:#f0f3f6}} small{{color:#666}}
 .note{{background:#fff8e1;border:1px solid #ffe082;padding:10px;border-radius:8px;font-size:13px}}
</style></head><body><div class=wrap>
<h1>📋 {REPORT_TITLE} <small>기준일 {g['date']}</small></h1>
<div class=cards>
 <div class=card><h3>규정 현황</h3><div class=big>
   <span class=ok>🟢 정상 {rc['ok']}</span><br>
   <span class=warn>🟡 확인필요 {rc['warn']}</span><br>
   <span class=fail>🔴 불일치 {rc['fail']}</span></div></div>
 <div class=card><h3>데이터 수집 상태</h3><div class=big>
   <span class=ok>🟢 정상 {sc['ok']}</span><br>
   <span class=warn>🟡 주의 {sc['warn']}</span><br>
   <span class=fail>🔴 실패 {sc['fail']}</span></div></div>
</div>
<div class=note>⚠ 이 시스템은 "변경 없음"이 아니라 <b>"최신 정보를 정상 확인했고 그 결과 변경 없음"</b>을 보증합니다.
 각 비교결과에는 Source 상태·최신성·마지막 정상수집일이 함께 표시됩니다. 최신성 미확인 항목은 "이상 없음"으로 간주하지 않습니다.</div>

<h2>B. 시스템(데이터 수집) 현황</h2>
<table><tr><th></th><th>Source</th><th>국가</th><th>상태</th><th>최신성</th><th>records</th>
 <th>마지막 정상수집</th><th>마지막 시도</th><th>메시지</th></tr>
{_health_html(g['health'])}</table>

<h2>A. 규정 비교 결과 (심각도순)</h2>
<table><tr><th></th><th>Source</th><th>작물</th><th>농약</th><th>국내(한국)</th><th>해외</th>
 <th>상태</th><th>Severity</th><th>신뢰도<br>(상태/최신성)</th><th>근거</th></tr>
{_rows_html(g['comps'])}</table>

<h2>알림 (규정 + 시스템)</h2><ul>{alerts_html}</ul>
<h2>WTO/SPS 변경예고 (Early warning)</h2><ul>{sps_html}</ul>
<p><small>생성: {db.now_iso()} · PoC v0.1</small></p>
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
