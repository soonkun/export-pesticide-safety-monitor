"""운영보고서 + 대시보드 생성 (§24·§25·§35·§36).

두 축을 분리해서 보여준다: (A) 규정 현황  (B) 데이터 수집(시스템) 현황.
최신성 미확인은 '이상 없음'으로 표시하지 않는다.
"""
from __future__ import annotations

import html
from datetime import date

from . import db
from .config import OUT_DIR, REPORT_TITLE, SOURCES
from .compare import classify_eping, dday
from .masters import COMMODITIES, PESTICIDES, member_label

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

    # eping 통보문 분류 — 알림과 같은 함수를 써서 화면/알림이 갈라지지 않게 한다
    eping = classify_eping(conn)

    # 담당자 조치사항 (의사결정)
    actions = {
        "update_guideline": [c for c in comps if c["item"] == "GUIDELINE" and c["status"] == "FOREIGN_CHANGED"],
        "no_export": [c for c in comps if c["item"] == "REGISTRATION"],
        "stale": [c for c in comps if c["item"] == "GUIDELINE" and c["status"] == "REVIEW_REQUIRED"],
        "unreflected": eping["urgent"],
        "upcoming": eping["prepare"],
    }
    return {
        "date": date.today().isoformat(),
        "health": health, "comps": comps, "alerts": alerts,
        "changes": changes, "sps": sps,
        "live": live, "eping": eping,
        "reg_counts": reg_counts, "sys_counts": sys_counts,
        "actions": actions,
        "reg_alerts": [a for a in alerts if a["category"] in ("REGULATION", "REGISTRATION")],
        "sys_alerts": [a for a in alerts if a["category"] == "SYSTEM"],
    }


def render_text(g: dict) -> str:
    """카카오/짧은 알림용 — 지침 대비 현행이 다른 건과 D-day 만."""
    a = g["actions"]
    changed = [c for c in g["comps"] if c["item"] == "GUIDELINE" and c["status"] == "FOREIGN_CHANGED"]
    lines = [f"[지침↔현행 대조] {g['date']}"]
    if a["unreflected"]:
        u = a["unreflected"][0]
        lines.append(f"🔴 미반영 {len(a['unreflected'])}건 — {u['member']} {u['pesticide_ko']} "
                     f"{u['entry_into_force']} 시행")
    if changed:
        c = changed[0]
        lines.append(f"🔴 지침≠현행 {len(changed)}건 — {c['source']} {c['commodity_ko']}/{c['pesticide_ko']} "
                     f"지침 {c.get('published_mrl')} → 현행 {c['foreign_mrl']}")
    if a["stale"]:
        lines.append(f"⚠ 최신성 확인 필요 {len(a['stale'])}건")
    if a["upcoming"]:
        p = a["upcoming"][0]
        lines.append(f"🕒 대비 {len(a['upcoming'])}건 — 최근접 {dday(p['days'])} {p['member']} {p['pesticide_ko']}")
    if len(lines) == 1:
        lines.append("지침 배포값과 현행 해외기준 일치 · 조치 없음")
    return "\n".join(lines)[:190]


SOURCE_LABEL = {"EU": "EU", "Japan": "일본", "Codex": "Codex"}
FFCR_GLOSSARY = ("http://www.ffcr.or.jp/en/zanryu/the-japanese-positive/"
                 "positive-list-system---glossary.html")

VERDICT = {   # 상태 → (배지, 설명)
    "MATCH": ("✅ 일치", "지침 배포값 = 현행"),
    "FOREIGN_CHANGED": ("🔴 다름", "지침 갱신 필요"),
    "REVIEW_REQUIRED": ("⚠ 확인필요", "현행 확인 불가"),
    "AMBIGUOUS": ("⚠ 판정불가", "수치 파싱 불가"),
}


def _esc(x) -> str:
    return html.escape(str(x)) if x else ""


def _verdict(c: dict) -> tuple[str, str]:
    badge, why = VERDICT.get(c["status"], (c["status"], ""))
    if c["status"] == "FOREIGN_CHANGED":
        why = "현행이 더 엄격 — 위반 위험" if c["severity"] == "CRITICAL" else "현행이 더 완화"
    return badge, why


def _basis_html(basis: str | None) -> str:
    """설정근거 — 일본은 'Ab2025' 같은 고시 코드, EU는 긴 각주 문장이라 잘라서 보여준다."""
    if not basis:
        return ""
    short = basis if len(basis) <= 42 else basis[:42].rstrip() + "…"
    return f'<b title="{_esc(basis)}">{_esc(short)}</b>'


def _why_html(c: dict) -> str:
    """근거와 시점. 없는 근거를 있는 것처럼 채우지 않는다."""
    bits = []
    if c.get("basis"):
        bits.append(f"설정근거 {_basis_html(c['basis'])}")
    if c.get("changed_at"):
        bits.append(_esc(c["changed_at"]))
    if c.get("source_url"):
        bits.append(f'<a href="{_esc(c["source_url"])}" target=_blank rel=noopener>원문 ↗</a>')
    ev = (c.get("evidence") or "").split("|")
    if len(ev) == 4 and ev[0]:
        sym, when, link, title = ev
        anchor = f'<a href="{_esc(link)}" target=_blank rel=noopener>{_esc(sym)}</a>' if link else _esc(sym)
        bits.append(f"통보문 {anchor}{f' · {_esc(when)} 시행' if when else ''}")
    if not bits:
        return "<span class=dim>근거자료 없음</span>"
    return " · ".join(bits)


def guideline_rows(comps: list[dict]) -> tuple[list[dict], list[dict]]:
    """지침 대조 결과를 (조치 필요, 일치 확인)으로 나눈다. 일치는 접어둔다 — 볼 이유가 없다."""
    rows = [c for c in comps if c["item"] == "GUIDELINE"]
    order = {(cm, pk): (ci, pi) for ci, cm in enumerate(COMMODITIES)
             for pi, pk in enumerate(PESTICIDES)}
    rank = {"FOREIGN_CHANGED": 0, "REVIEW_REQUIRED": 1, "AMBIGUOUS": 1, "MATCH": 2}
    rows.sort(key=lambda c: (rank.get(c["status"], 3),
                             order.get((c["commodity_ko"], c["pesticide_ko"]), (99, 99))))
    return ([c for c in rows if c["status"] != "MATCH"],
            [c for c in rows if c["status"] == "MATCH"])


def _match_html(rows: list[dict]) -> str:
    """일치 확인 건 — 한 줄씩. 근거만 남긴다."""
    if not rows:
        return "<p class=dim>없음</p>"
    return "<ul>" + "".join(
        f"<li>{_esc(c['commodity_ko'])} · {_esc(c['pesticide_ko'])} · "
        f"{_esc(SOURCE_LABEL.get(c['source'], c['source']))} — "
        f"<b>{_esc(c['foreign_mrl'])}</b> <span class=dim>"
        + (f"근거 {_basis_html(c['basis'])} · " if c.get("basis") else "")
        + f"{_esc(c.get('changed_at'))}</span>"
        + (f' <a href="{_esc(c["source_url"])}" target=_blank rel=noopener>↗</a>'
           if c.get("source_url") else "") + "</li>"
        for c in rows) + "</ul>"


def _rows_html(rows: list[dict]) -> str:
    """지침 배포 해외기준 vs 현행 해외기준 — 이 시스템의 본체."""
    if not rows:
        return "<p class=dim>✅ 지침에 실린 해외기준이 모두 현행과 일치합니다.</p>"

    out = []
    for c in rows:
        badge, why = _verdict(c)
        b = _reg_bucket(c["status"])
        pub = _esc(c.get("published_mrl")) or "-"
        cur = _esc(c["foreign_mrl"]) or "-"
        conf = "" if c["data_confidence"] == "HIGH" else " <span class=dim>◦최신성 미확인</span>"
        note = f'<div class=note>{_esc(c["detail"])}</div>' if c["status"] != "MATCH" else ""
        out.append(f"""<div class="row {b}">
 <div class=who><b>{_esc(c['commodity_ko'])}</b> · {_esc(c['pesticide_ko'])}
   <small>{_esc(c['pesticide_en'])}</small></div>
 <div class=cty>{_esc(SOURCE_LABEL.get(c['source'], c['source']))}</div>
 <div class=val><span class=lbl>지침</span><span class=pub>{pub}</span>
   <span class=arw>→</span><span class=lbl>현행</span><span class=cur>{cur}</span>{conf}</div>
 <div class=vd><b>{badge}</b><br><small>{_esc(why)}</small></div>
 <div class=why>{_why_html(c)}</div>
 {note}</div>""")
    return "".join(out)


def _prepare_html(prepare: list[dict]) -> str:
    if not prepare:
        return "<p class=dim>시행 예정으로 확인된 변경 없음</p>"
    out = []
    for p in prepare:
        soon = " soon" if p["days"] <= 30 else ""
        link = (f'<a href="{_esc(p["link"])}" target=_blank rel=noopener>{_esc(p["symbol"])} ↗</a>'
                if p.get("link") else _esc(p["symbol"]))
        out.append(f"""<div class="row prep{soon}">
 <div class=dd>{dday(p['days'])}</div>
 <div class=who>{member_label(p['member'])} · <b>{_esc(p['pesticide_ko'])}</b></div>
 <div class=val><span class=lbl>{_esc(p['basis'])}</span> {_esc(p['when'])}</div>
 <div class=why>{link} <small>{_esc((p['title'] or '')[:100])}</small></div></div>""")
    return "".join(out)


def _unreflected_html(urgent: list[dict]) -> str:
    if not urgent:
        return ""
    out = []
    for u in urgent:
        link = (f'<a href="{_esc(u["link"])}" target=_blank rel=noopener>{_esc(u["symbol"])} ↗</a>'
                if u.get("link") else _esc(u["symbol"]))
        out.append(f"""<div class="row fail">
 <div class=who>{member_label(u['member'])} · <b>{_esc(u['pesticide_ko'])}</b></div>
 <div class=cty>{_esc(u['entry_into_force'])} 시행</div>
 <div class=val><b>{dday(u['days'])}</b> 경과</div>
 <div class=vd><b>🔴 미반영</b><br><small>즉시 수정</small></div>
 <div class=why>{link} <small>{_esc((u['title'] or '')[:100])}</small><br>
   <small>{_esc(u['source'])} 마지막 정상수집 {_esc(u['last_success'])} &lt; 발효일 {_esc(u['entry_into_force'])}</small></div>
 </div>""")
    return f'<h2>🔴 시행됐는데 반영 근거 없음 — 즉시 수정</h2><div class=list>{"".join(out)}</div>'


def _chips_html(health: list[dict]) -> str:
    seen = {h["source"]: h for h in health}
    out = []
    for name in SOURCES:
        h = seen.get(name)
        st = (h["status"] if h else "UNKNOWN") or "UNKNOWN"
        msg = (h["status_message"] if h else "") or ""
        when = (h["last_success_at"] if h and h["last_success_at"] else "없음")[:16]
        out.append(f'<span class="chip {_sys_bucket(st)}" title="{_esc(st)} · 마지막 정상수집 '
                   f'{_esc(when)} {_esc(msg[:120])}">{DOT[_sys_bucket(st)]} {name}</span>')
    return "".join(out)


def _margin_html(comps: list[dict]) -> str:
    rows = [c for c in comps if c["item"] == "EXPORT_MARGIN"]
    if not rows:
        return "<p class=dim>없음</p>"
    return "<ul>" + "".join(
        f"<li>{_esc(c['commodity_ko'])} · {_esc(c['pesticide_ko'])} — 국내 {_esc(c['korea_mrl'])} &gt; "
        f"{_esc(SOURCE_LABEL.get(c['source'], c['source']))} 현행 {_esc(c['foreign_mrl'])}</li>"
        for c in rows) + "</ul>"


def _fold(title: str, n: int, body: str) -> str:
    return f"<details><summary>{title} <b>{n}</b></summary>{body}</details>"


def render_html(g: dict) -> str:
    a = g["actions"]
    diff, same = guideline_rows(g["comps"])
    todo_n = len(a["unreflected"]) + len(a["no_export"]) + len(diff)
    hid = g["eping"]["hidden"]
    soon = any(p["days"] <= 30 for p in a["upcoming"])

    alerts_html = "".join(
        f"<li><b>[{_esc(x['severity'])}]</b> {_esc(x['title'])}"
        f"<br><small>{_esc((x['body'] or '')[:220])}</small></li>"
        for x in g["alerts"][:30]) or "<li>없음</li>"
    sps_html = "".join(
        f"<li><small>{_esc((s['distribution_date'] or '')[:10])} · {member_label(s['member'])}</small> "
        f"{_esc((s['title'] or '')[:110])}</li>"
        for s in g["sps"][:15]) or "<li>없음</li>"

    return f"""<!doctype html><html lang=ko><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{REPORT_TITLE} {g['date']}</title>
<style>
 :root{{--line:#e2e6ea;--dim:#7a848e;--ok:#0a7d33;--warn:#a86500;--fail:#c0281f;--bg:#f6f7f9}}
 *{{box-sizing:border-box}}
 body{{font-family:-apple-system,BlinkMacSystemFont,'Noto Sans KR','Malgun Gothic',sans-serif;
      margin:0;background:var(--bg);color:#16191c;font-size:15px;line-height:1.5;
      -webkit-text-size-adjust:100%}}
 .wrap{{max-width:940px;margin:0 auto;padding:12px 12px 40px}}
 h1{{font-size:17px;margin:2px 0 4px}} h1 small{{font-weight:400;color:var(--dim)}}
 h2{{font-size:14px;margin:22px 0 8px;color:#2d3a46}}
 .purpose{{background:#eef3f8;border:1px solid #d3e0ec;border-radius:8px;padding:8px 10px;
          font-size:12.5px;color:#3a4a58;margin:8px 0 4px}}
 .strip{{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin:10px 0}}
 .chip,.count{{background:#fff;border:1px solid var(--line);border-radius:99px;
              padding:3px 10px;font-size:12.5px;white-space:nowrap}}
 .count{{font-weight:700;border-radius:7px}}
 .count.hit{{background:#fdecea;border-color:#f0b8b2;color:var(--fail)}}
 .chip.fail{{background:#fff5f4;border-color:#f0b8b2}} .chip.warn{{border-color:#eed9a8}}
 .list{{display:flex;flex-direction:column;gap:8px}}
 .row{{background:#fff;border:1px solid var(--line);border-left:4px solid var(--line);
      border-radius:10px;padding:10px 12px;display:grid;gap:2px 12px;
      grid-template-columns:minmax(150px,1.5fr) 62px minmax(150px,1.4fr) 108px;
      align-items:baseline}}
 .row.fail{{border-left-color:var(--fail)}} .row.warn{{border-left-color:var(--warn)}}
 .row.ok{{border-left-color:#cfe3d5}}
 .row .who small{{color:var(--dim);font-size:11.5px;display:block}}
 .row .cty{{color:var(--dim);font-size:12.5px}}
 .row .val{{font-variant-numeric:tabular-nums}}
 .lbl{{color:var(--dim);font-size:11px;margin-right:3px}}
 .pub{{text-decoration:line-through;color:var(--dim)}}
 .arw{{color:var(--dim);margin:0 6px}}
 .cur{{font-weight:700;font-size:16px}}
 .row.fail .cur{{color:var(--fail)}}
 .row .vd{{text-align:right;font-size:12.5px}} .row .vd small{{color:var(--dim)}}
 .row .why{{grid-column:1/-1;border-top:1px dashed var(--line);margin-top:6px;padding-top:6px;
           font-size:12px;color:#4a5560}}
 .row .note{{grid-column:1/-1;font-size:12.5px;color:var(--fail);margin-top:4px}}
 .row.prep{{grid-template-columns:64px minmax(140px,1.4fr) minmax(120px,1fr)}}
 .row.prep .dd{{font-weight:700;color:var(--warn)}}
 .row.prep.soon{{border-left-color:var(--fail)}} .row.prep.soon .dd{{color:var(--fail)}}
 .dim{{color:var(--dim)}}
 a{{color:#1a5fa8}}
 details{{background:#fff;border:1px solid var(--line);border-radius:10px;margin:8px 0;padding:8px 12px}}
 summary{{cursor:pointer;font-size:13.5px;color:#2d3a46;padding:2px 0}}
 details ul{{margin:8px 0 2px;padding-left:18px;font-size:12.5px}} details li{{margin:4px 0}}
 .hint{{color:var(--dim);font-size:11.5px;margin:8px 0 2px}}
 .foot{{color:var(--dim);font-size:11.5px;margin-top:18px}}
 @media(max-width:640px){{
   .wrap{{padding:10px 10px 32px}}
   .row,.row.prep{{grid-template-columns:1fr auto;gap:2px 8px}}
   .row .who{{grid-column:1/-1}} .row .cty{{font-size:12px}}
   .row .vd{{text-align:left}} .row.prep .dd{{grid-column:1}}
   summary{{padding:6px 0}}
 }}
</style></head><body><div class=wrap>
<h1>📋 {REPORT_TITLE} <small>{g['date']}</small></h1>
<div class=purpose>이 보고서는 <b>수출농산물 농약 안전사용지침에 실린 해외기준</b>과
 <b>수입국의 현행 해외기준</b>이 같은지를 대조합니다. 다르면 근거와 시점을 함께 제시합니다.
 (국내 MRL 비교는 부차 참고 항목입니다.)</div>
<div class=strip>
 <span class="count {'hit' if todo_n else ''}">조치 {todo_n}</span>
 <span class="count {'hit' if soon else ''}">대비 {len(a['upcoming'])}</span>
 {_chips_html(g['health'])}
</div>

{_unreflected_html(a['unreflected'])}

<h2>지침 배포 해외기준 ↔ 현행 해외기준</h2>
<div class=list>{_rows_html(diff)}</div>
{_fold('✅ 일치 확인 (조치 없음)', len(same), _match_html(same))}

<h2>대비 필요 (시행 예정)</h2>
<div class=list>{_prepare_html(a['upcoming'])}</div>
<p class=hint>숨김 {sum(hid.values())}건 — 반영 확인 {hid['reflected']} ·
 지침 대상국 아님 {hid['out_of_scope']} · 시행일 미정 {hid['undated']}.
 이미 시행됐고 현행 수집에 반영된 통보문은 조치할 것이 없어 표시하지 않습니다.</p>

{_fold('📌 참고 · 국내 MRL이 현행 해외기준보다 높은 건', len([c for c in g['comps'] if c['item'] == 'EXPORT_MARGIN']), _margin_html(g['comps']))}
{_fold('🔔 알림', len(g['alerts']), f'<ul>{alerts_html}</ul>')}
{_fold('📄 SPS 통보문 (최근)', len(g['sps']), f'<ul>{sps_html}</ul>')}
<p class=foot>설정근거 코드(Ab####)는 일본 FFCR 표기입니다 —
 <a href="{FFCR_GLOSSARY}" target=_blank rel=noopener>용어 설명 ↗</a>.
 "변경 없음"이 아니라 "최신 정보를 정상 확인했고 그 결과 변경 없음"을 뜻합니다. · 생성 {db.now_iso()}</p>
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
