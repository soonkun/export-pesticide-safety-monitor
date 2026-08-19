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
GET /ops         관제·테스트 콘솔 (수동 실행 / 소스별 점검 / 실행로그)

전 경로 HTTP Basic 인증(.env: OPS_USER/OPS_PASS). 공개(Cloudflare Tunnel) 전제이므로 필수.
"""
from __future__ import annotations

import base64
import os
import secrets
import subprocess
import sys
import threading
from collections import deque

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from . import db, report
from .config import BASE_DIR, SOURCES

OPS_USER = os.getenv("OPS_USER", "admin")
OPS_PASS = os.getenv("OPS_PASS", "")
if not OPS_PASS:
    raise RuntimeError(
        "OPS_PASS 미설정. 관제 페이지는 외부에 공개되므로 인증 없이 기동하지 않습니다. "
        ".env 에 OPS_USER/OPS_PASS 를 설정하세요 (scripts/install-systemd.sh 가 자동 생성).")

app = FastAPI(title="수출농산물 농약기준 모니터링 API", version="0.1.0")

_c = db.connect()             # 첫 기동 시 빈 DB여도 대시보드가 뜨도록 스키마 보장
db.init_db(_c)
_c.close()


@app.middleware("http")
async def _basic_auth(request, call_next):
    hdr = request.headers.get("authorization", "")
    ok = False
    if hdr.startswith("Basic "):
        try:
            user, _, pw = base64.b64decode(hdr[6:]).decode("utf-8").partition(":")
            ok = (secrets.compare_digest(user, OPS_USER)
                  and secrets.compare_digest(pw, OPS_PASS))
        except Exception:
            ok = False
    if not ok:
        return PlainTextResponse("Unauthorized", status_code=401,
                                 headers={"WWW-Authenticate": 'Basic realm="pesticide-monitor"'})
    return await call_next(request)


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


# ---------------------------------------------------------------- 관제/테스트 콘솔
# 파이프라인은 별도 프로세스로 돌린다: DB 잠금 경합 없이 CLI 진입점을 그대로 재사용.
_job = {"running": False, "cmd": "", "started": "", "finished": "", "returncode": None}
_log: deque[str] = deque(maxlen=500)
_lock = threading.Lock()


def _spawn(args: list[str]) -> bool:
    """파이프라인 서브프로세스 시작. 이미 실행 중이면 False."""
    with _lock:
        if _job["running"]:
            return False
        _job.update(running=True, cmd=" ".join(args) or "(전체 실행)",
                    started=db.now_iso(), finished="", returncode=None)
        _log.clear()

    def worker():
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "src.pipeline", *args], cwd=BASE_DIR,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                env={**os.environ, "PYTHONUNBUFFERED": "1"})
            for line in proc.stdout:
                _log.append(line.rstrip())
            _job["returncode"] = proc.wait()
        except Exception as e:
            _log.append(f"[실행 오류] {type(e).__name__}: {e}")
            _job["returncode"] = -1
        finally:
            _job["finished"] = db.now_iso()
            _job["running"] = False

    threading.Thread(target=worker, daemon=True).start()
    return True


@app.post("/ops/run")
def ops_run(notify: int = Query(0, description="1이면 이메일/카카오 발송까지")):
    if not _spawn([] if notify else ["--no-notify"]):
        return JSONResponse({"error": "이미 실행 중"}, status_code=409)
    return {"started": True}


@app.post("/ops/test/{name}")
def ops_test(name: str):
    if name not in SOURCES:
        return JSONResponse({"error": f"unknown source: {name}"}, status_code=404)
    if not _spawn(["--only", name]):
        return JSONResponse({"error": "이미 실행 중"}, status_code=409)
    return {"started": True}


@app.get("/ops/job")
def ops_job():
    return {**_job, "log": list(_log)}


@app.get("/ops", response_class=HTMLResponse)
def ops_page():
    buttons = "".join(
        f"<button class=src data-src='{n}'>{n} 점검</button>" for n in SOURCES)
    return HTMLResponse(f"""<!doctype html><html lang=ko><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>관제 콘솔 · 수출농산물 농약기준 모니터링</title>
<style>
 body{{font-family:-apple-system,'Noto Sans KR',sans-serif;margin:0;background:#f4f6f8;color:#1a1a1a}}
 .wrap{{max-width:1100px;margin:0 auto;padding:16px}}
 h1{{font-size:20px}} h2{{font-size:16px;margin-top:24px;border-left:4px solid #345;padding-left:8px}}
 button{{font:inherit;padding:7px 12px;border:1px solid #c3c9d0;border-radius:6px;background:#fff;cursor:pointer}}
 button:hover{{background:#eef2f6}} button:disabled{{opacity:.45;cursor:not-allowed}}
 button.primary{{background:#1f5fa8;border-color:#1f5fa8;color:#fff}}
 .bar{{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:10px 0}}
 table{{width:100%;border-collapse:collapse;background:#fff;font-size:13px;border-radius:8px;overflow:hidden}}
 th,td{{border:1px solid #e3e6ea;padding:6px 8px;text-align:left}} th{{background:#f0f3f6}}
 pre{{background:#10151a;color:#d6e2ee;padding:12px;border-radius:8px;font-size:12.5px;
      height:340px;overflow:auto;white-space:pre-wrap;margin:0}}
 .st{{font-weight:700}} small{{color:#666}}
</style></head><body><div class=wrap>
<h1>🛠 관제 콘솔 <small>수출농산물 농약기준 모니터링</small></h1>
<div class=bar>
 <button class=primary id=run>전체 실행 (수집→비교→보고서)</button>
 <button id=runNotify>전체 실행 + 알림발송</button>
 {buttons}
 <a href="/" target=_blank><button>📋 대시보드</button></a>
</div>
<h2>실행 상태</h2>
<p id=jobline><small>불러오는 중…</small></p>
<pre id=log>로그 없음</pre>
<h2>Source 상태</h2>
<table id=tbl><tr><th>Source</th><th>국가</th><th>상태</th><th>최신성</th><th>records</th>
 <th>마지막 정상수집</th><th>응답(s)</th><th>메시지</th></tr></table>
<script>
const DOT = s => ({{HEALTHY:'🟢',WARNING:'🟡',STALE:'🟡',AGING:'🟡'}}[s] || '🔴');
async function post(u) {{
  const r = await fetch(u, {{method:'POST'}});
  if (!r.ok) alert((await r.json()).error);
  poll();
}}
document.getElementById('run').onclick = () => post('/ops/run');
document.getElementById('runNotify').onclick = () => post('/ops/run?notify=1');
document.querySelectorAll('button.src').forEach(b =>
  b.onclick = () => post('/ops/test/' + b.dataset.src));

async function poll() {{
  const j = await (await fetch('/ops/job')).json();
  document.getElementById('jobline').innerHTML = j.started
    ? `<span class=st>${{j.running ? '⏳ 실행 중' : (j.returncode === 0 ? '✅ 완료' : '❌ 실패(code ' + j.returncode + ')')}}</span>`
      + ` — <code>${{j.cmd}}</code> <small>시작 ${{j.started}} ${{j.finished ? '· 종료 ' + j.finished : ''}}</small>`
    : '<small>아직 실행 이력 없음</small>';
  document.getElementById('log').textContent = j.log.join('\\n') || '로그 없음';
  document.querySelectorAll('button').forEach(b => {{ if (b.id || b.classList.contains('src')) b.disabled = j.running; }});
  if (!j.running) sources();
}}
async function sources() {{
  const rows = await (await fetch('/sources')).json();
  document.getElementById('tbl').innerHTML =
    '<tr><th>Source</th><th>국가</th><th>상태</th><th>최신성</th><th>records</th>'
    + '<th>마지막 정상수집</th><th>응답(s)</th><th>메시지</th></tr>'
    + rows.map(r => `<tr><td>${{DOT(r.status)}} <b>${{r.name}}</b></td><td>${{r.country}}</td>`
      + `<td>${{r.status || 'UNKNOWN'}}</td><td>${{r.freshness || '-'}}</td>`
      + `<td>${{r.number_of_records ?? '-'}}</td><td><small>${{(r.last_success_at || '없음').slice(0,16)}}</small></td>`
      + `<td>${{r.response_time ?? '-'}}</td><td><small>${{(r.status_message || '').slice(0,120)}}</small></td></tr>`).join('');
}}
poll(); setInterval(poll, 2000);
</script>
<p><small>기록: 모든 실행은 collection_runs / source_health 테이블에 남습니다. 인증: HTTP Basic (.env OPS_USER/OPS_PASS)</small></p>
</div></body></html>""")
