"""상태 조회 API + 대시보드 (§33).

실행: python -m src.serve   (또는 uvicorn src.api:app --port 8000)
GET /            대시보드 HTML
GET /status      전체 시스템 상태 요약
GET /sources     Source별 상태
GET /sources/{name}/health
GET /changes     최근 해외 규정 변경
GET /comparisons 비교결과 (query: severity, source)
GET /alerts      검토 필요사항
GET /history     특정 작물·농약 변경이력 (query: pesticide_en, commodity_ko)
"""
from __future__ import annotations

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse

from . import db, report
from .config import SOURCES

app = FastAPI(title="수출농산물 농약기준 모니터링 API", version="0.1.0")


def _conn():
    return db.connect()


@app.get("/", response_class=HTMLResponse)
def dashboard():
    conn = _conn()
    g = report.gather(conn)
    html_doc = report.render_html(g)
    conn.close()
    return HTMLResponse(html_doc)


@app.get("/status")
def status():
    conn = _conn()
    g = report.gather(conn)
    conn.close()
    return {"date": g["date"], "regulation": g["reg_counts"], "system": g["sys_counts"],
            "reg_alerts": len(g["reg_alerts"]), "sys_alerts": len(g["sys_alerts"])}


@app.get("/sources")
def sources():
    conn = _conn()
    rows = {r["source"]: dict(r) for r in conn.execute("SELECT * FROM source_health").fetchall()}
    conn.close()
    return [{"name": n, **SOURCES[n], **rows.get(n, {"status": "UNKNOWN"})} for n in SOURCES]


@app.get("/sources/{name}/health")
def source_health(name: str):
    conn = _conn()
    r = conn.execute("SELECT * FROM source_health WHERE source=?", (name,)).fetchone()
    runs = [dict(x) for x in conn.execute(
        "SELECT * FROM collection_runs WHERE source=? ORDER BY run_id DESC LIMIT 10", (name,)).fetchall()]
    conn.close()
    if not r:
        return JSONResponse({"error": "unknown source"}, status_code=404)
    return {"health": dict(r), "recent_runs": runs}


@app.get("/changes")
def changes():
    conn = _conn()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM change_events ORDER BY id DESC LIMIT 100").fetchall()]
    conn.close()
    return rows


@app.get("/comparisons")
def comparisons(severity: str | None = Query(None), source: str | None = Query(None)):
    conn = _conn()
    q = "SELECT * FROM comparison_results WHERE 1=1"
    args = []
    if severity:
        q += " AND severity=?"; args.append(severity)
    if source:
        q += " AND source=?"; args.append(source)
    rows = [dict(r) for r in conn.execute(q, args).fetchall()]
    conn.close()
    return rows


@app.get("/alerts")
def alerts():
    conn = _conn()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM alerts WHERE acknowledged=0 ORDER BY id DESC").fetchall()]
    conn.close()
    return rows


@app.get("/history")
def history(pesticide_en: str = Query(...), commodity_ko: str = Query(...)):
    conn = _conn()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM mrl_history WHERE pesticide_en=? AND commodity_ko=? ORDER BY observed_at",
        (pesticide_en, commodity_ko)).fetchall()]
    conn.close()
    return rows
