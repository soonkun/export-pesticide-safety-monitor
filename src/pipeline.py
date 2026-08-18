"""전체 파이프라인 오케스트레이션.

공식 수집 → 표준화 → 변경탐지/비교 → 시스템 상태검증 → 보고서 → 알림.
매일 실행 진입점: python -m src.pipeline
"""
from __future__ import annotations

import sys

try:  # 콘솔이 cp949여도 한글/기호 출력이 깨지지 않도록
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from . import db, report
from .collectors import ALL_COLLECTORS


def collect_all(conn) -> list[dict]:
    runs = []
    for cls in ALL_COLLECTORS:
        c = cls()
        try:
            summary = c.run(conn)
        except Exception as e:  # collector.run 내부에서 대부분 처리되지만 안전망
            summary = {"source": c.name, "status": "FAILED", "error": str(e)}
        runs.append(summary)
        print(f"  - {summary['source']:6s} {summary['status']:18s} "
              f"records={summary.get('records', 0)} fresh={summary.get('freshness','')} "
              f"{summary.get('error') or ''}")
    return runs


def run_daily(notify: bool = True) -> dict:
    conn = db.connect()
    db.init_db(conn)
    conn.execute("DELETE FROM alerts")   # 알림은 매 실행마다 현재 상태로 재생성(누적 방지)
    conn.commit()
    print("[1/4] 공식 데이터 수집 …")
    runs = collect_all(conn)
    print("[2/4] 표준화·변경탐지·비교 …")
    from .compare import run_comparisons
    res = run_comparisons(conn)
    print(f"      비교결과 {len(res['comparisons'])}건 · 변경예고 {len(res['upcoming'])}건")
    print("[3/4] 보고서 생성 …")
    rep = report.build(conn)
    print(f"      대시보드: {rep['dashboard_path']}")
    if notify:
        print("[4/4] 알림 발송 …")
        from .notify import dispatch
        for ch, ok, msg in dispatch(rep):
            print(f"  - {ch:6s} {'OK ' if ok else 'SKIP/FAIL'} {msg}")
    else:
        print("[4/4] 알림 생략(--no-notify)")
    conn.close()
    return rep


if __name__ == "__main__":
    run_daily(notify="--no-notify" not in sys.argv)
