"""SQLite 스키마 및 헬퍼 (§9·§14·§18·§28·§32).

PoC 범위의 핵심 테이블만 구현. 원본 보존/이력/헬스/알림을 포함한다.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .config import DB_PATH


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
  name TEXT PRIMARY KEY, country TEXT, kind TEXT, authoritative INTEGER,
  interval_days INTEGER
);

-- 소스별 현재 상태 스냅샷 (§18)
CREATE TABLE IF NOT EXISTS source_health (
  source TEXT PRIMARY KEY,
  latest_attempt_at TEXT, last_success_at TEXT, last_failure_at TEXT, last_data_date TEXT,
  expected_update_interval INTEGER, consecutive_failures INTEGER DEFAULT 0,
  http_status INTEGER, response_time REAL,
  number_of_records INTEGER, previous_number_of_records INTEGER,
  schema_hash TEXT, content_hash TEXT,
  collector_version TEXT, parser_version TEXT,
  status TEXT, status_message TEXT, freshness TEXT
);

-- 모든 수집 로그 (§28)
CREATE TABLE IF NOT EXISTS collection_runs (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT, started_at TEXT, finished_at TEXT, status TEXT,
  http_status INTEGER, records_received INTEGER, records_valid INTEGER,
  records_invalid INTEGER, schema_changed INTEGER DEFAULT 0,
  error_type TEXT, error_message TEXT, retry_count INTEGER DEFAULT 0
);

-- 원본 스냅샷 (§9)
CREATE TABLE IF NOT EXISTS raw_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT, url TEXT, retrieved_at TEXT, http_status INTEGER,
  content_type TEXT, content_hash TEXT, file_hash TEXT,
  source_version TEXT, effective_date TEXT, raw_file_path TEXT
);

-- RDA 지침값 (국내 한국 MRL + 캐시된 외국 MRL) : 성분×작물×대상국
CREATE TABLE IF NOT EXISTS rda_guidelines (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  target_country TEXT, commodity_ko TEXT, pesticide_ko TEXT,
  product_name TEXT, korea_mrl TEXT, foreign_cached_mrl TEXT,
  uses TEXT, retrieved_at TEXT,
  UNIQUE(target_country, commodity_ko, product_name)
);

-- 해외 라이브 MRL : 소스×성분×작물
CREATE TABLE IF NOT EXISTS foreign_mrls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT, pesticide_en TEXT, commodity_ko TEXT, commodity_src TEXT,
  mrl_kind TEXT, mrl_value REAL, mrl_display TEXT, is_default INTEGER,
  effective_date TEXT, note TEXT, source_url TEXT, basis TEXT, retrieved_at TEXT,
  UNIQUE(source, pesticide_en, commodity_ko)
);

-- MRL 이력 (§13) : 값이 바뀔 때마다 append
CREATE TABLE IF NOT EXISTS mrl_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT, pesticide_en TEXT, commodity_ko TEXT,
  mrl_display TEXT, mrl_value REAL, observed_at TEXT
);

-- 비교 결과 (§3·§23)
CREATE TABLE IF NOT EXISTS comparison_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_at TEXT, source TEXT, pesticide_ko TEXT, pesticide_en TEXT,
  commodity_ko TEXT, item TEXT, status TEXT, severity TEXT,
  korea_mrl TEXT, foreign_mrl TEXT, detail TEXT,
  data_confidence TEXT, source_status TEXT, source_freshness TEXT,
  last_success_at TEXT, data_date TEXT
);

-- 변경 이벤트 (§13·§27)
CREATE TABLE IF NOT EXISTS change_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  detected_at TEXT, source TEXT, pesticide_en TEXT, commodity_ko TEXT,
  kind TEXT, old_value TEXT, new_value TEXT, note TEXT
);

-- 농약 등록/승인 상태 (§14, 수출 가부 판정)
CREATE TABLE IF NOT EXISTS registrations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT, pesticide_en TEXT, status TEXT,
  approval_date TEXT, expiry_date TEXT, retrieved_at TEXT,
  UNIQUE(source, pesticide_en)
);
CREATE TABLE IF NOT EXISTS registration_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT, pesticide_en TEXT, status TEXT, observed_at TEXT
);

-- SPS 통보문 (§16, WTO 변경예고)
CREATE TABLE IF NOT EXISTS sps_notifications (
  id TEXT PRIMARY KEY, area TEXT, notif_type TEXT, member TEXT,
  distribution_date TEXT, comment_deadline TEXT, entry_into_force TEXT,
  document_symbol TEXT, title TEXT, products TEXT, keywords TEXT,
  link TEXT, retrieved_at TEXT
);

-- 알림 (§26)
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT, category TEXT, severity TEXT, title TEXT, body TEXT,
  source TEXT, acknowledged INTEGER DEFAULT 0
);
"""


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for ddl in ("ALTER TABLE foreign_mrls ADD COLUMN note TEXT",
                "ALTER TABLE foreign_mrls ADD COLUMN source_url TEXT",
                "ALTER TABLE foreign_mrls ADD COLUMN basis TEXT",
                "ALTER TABLE comparison_results ADD COLUMN published_mrl TEXT",
                "ALTER TABLE comparison_results ADD COLUMN source_url TEXT",
                "ALTER TABLE comparison_results ADD COLUMN basis TEXT",
                "ALTER TABLE comparison_results ADD COLUMN changed_at TEXT",
                "ALTER TABLE comparison_results ADD COLUMN evidence TEXT"):
        try:            # 기존 DB 마이그레이션 (컬럼이 이미 있으면 무시)
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass
    from .config import SOURCES
    for name, meta in SOURCES.items():
        conn.execute(
            "INSERT OR REPLACE INTO sources(name,country,kind,authoritative,interval_days)"
            " VALUES(?,?,?,?,?)",
            (name, meta["country"], meta["kind"], int(meta["authoritative"]), meta["interval_days"]),
        )
    conn.commit()


def add_snapshot(conn, **kw) -> None:
    cols = ("source", "url", "retrieved_at", "http_status", "content_type",
            "content_hash", "file_hash", "source_version", "effective_date", "raw_file_path")
    conn.execute(
        f"INSERT INTO raw_snapshots({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        tuple(kw.get(c) for c in cols),
    )


def add_run(conn, **kw) -> int:
    cols = ("source", "started_at", "finished_at", "status", "http_status",
            "records_received", "records_valid", "records_invalid", "schema_changed",
            "error_type", "error_message", "retry_count")
    cur = conn.execute(
        f"INSERT INTO collection_runs({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        tuple(kw.get(c) for c in cols),
    )
    return cur.lastrowid


def upsert_health(conn, source: str, **kw) -> None:
    prev = conn.execute("SELECT number_of_records FROM source_health WHERE source=?",
                        (source,)).fetchone()
    if prev is not None and kw.get("number_of_records") is not None:
        kw.setdefault("previous_number_of_records", prev["number_of_records"])
    fields = ["source"] + list(kw.keys())
    placeholders = ",".join("?" * len(fields))
    updates = ",".join(f"{k}=excluded.{k}" for k in kw)
    conn.execute(
        f"INSERT INTO source_health({','.join(fields)}) VALUES ({placeholders}) "
        f"ON CONFLICT(source) DO UPDATE SET {updates}",
        tuple([source] + list(kw.values())),
    )


def prune_foreign_mrls(conn, source: str, before: str) -> int:
    """이번 수집에서 다시 확인되지 않은 그 소스의 기준값을 지운다.

    upsert 만 하면 소스가 기준을 삭제하거나 해석 규칙이 바뀌어도 옛 값이 남아
    "지침=현행 일치"로 계속 보고된다(실측: 대만 파서 수정 후 잘못된 값 2건이 살아남음).
    수집이 성공했을 때만 호출한다 — 실패 시 지우면 멀쩡한 값을 잃는다.
    """
    cur = conn.execute("DELETE FROM foreign_mrls WHERE source=? AND retrieved_at < ?",
                       (source, before))
    return cur.rowcount


def record_registration(conn, *, source, pesticide_en, status, approval_date=None,
                        expiry_date=None) -> None:
    """등록상태 upsert + 상태 변경 시 history/change_events(REGISTRATION_CHANGED) 기록 (§14)."""
    ts = now_iso()
    prev = conn.execute("SELECT status FROM registrations WHERE source=? AND pesticide_en=?",
                        (source, pesticide_en)).fetchone()
    conn.execute(
        "INSERT INTO registrations(source,pesticide_en,status,approval_date,expiry_date,retrieved_at)"
        " VALUES(?,?,?,?,?,?) ON CONFLICT(source,pesticide_en) DO UPDATE SET "
        "status=excluded.status,approval_date=excluded.approval_date,"
        "expiry_date=excluded.expiry_date,retrieved_at=excluded.retrieved_at",
        (source, pesticide_en, status, approval_date, expiry_date, ts))
    if prev is None or prev["status"] != status:
        conn.execute("INSERT INTO registration_history(source,pesticide_en,status,observed_at)"
                     " VALUES(?,?,?,?)", (source, pesticide_en, status, ts))
        if prev is not None:
            conn.execute(
                "INSERT INTO change_events(detected_at,source,pesticide_en,commodity_ko,kind,old_value,new_value,note)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (ts, source, pesticide_en, None, "REGISTRATION_CHANGED",
                 prev["status"], status, "등록상태 변경 관측"))


def add_alert(conn, *, category, severity, title, body, source=None) -> None:
    conn.execute(
        "INSERT INTO alerts(created_at,category,severity,title,body,source) VALUES(?,?,?,?,?,?)",
        (now_iso(), category, severity, title, body, source),
    )


def record_foreign_mrl(conn, *, source, pesticide_en, commodity_ko, commodity_src,
                       mrl, effective_date=None, note=None, source_url=None, basis=None) -> None:
    """foreign_mrls upsert + 값 변경 시 mrl_history/change_events 기록 (§13·§27)."""
    ts = now_iso()
    prev = conn.execute(
        "SELECT mrl_value,mrl_display FROM foreign_mrls WHERE source=? AND pesticide_en=? AND commodity_ko=?",
        (source, pesticide_en, commodity_ko)).fetchone()
    conn.execute(
        "INSERT INTO foreign_mrls(source,pesticide_en,commodity_ko,commodity_src,mrl_kind,"
        "mrl_value,mrl_display,is_default,effective_date,note,source_url,basis,retrieved_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(source,pesticide_en,commodity_ko) DO UPDATE SET "
        "commodity_src=excluded.commodity_src,mrl_kind=excluded.mrl_kind,mrl_value=excluded.mrl_value,"
        "mrl_display=excluded.mrl_display,is_default=excluded.is_default,"
        "effective_date=excluded.effective_date,note=excluded.note,source_url=excluded.source_url,"
        "basis=excluded.basis,retrieved_at=excluded.retrieved_at",
        (source, pesticide_en, commodity_ko, commodity_src, mrl.kind.value,
         mrl.value, mrl.display(), int(mrl.is_default), effective_date, note, source_url, basis, ts),
    )
    if prev is None or (prev["mrl_display"] != mrl.display()):
        conn.execute(
            "INSERT INTO mrl_history(source,pesticide_en,commodity_ko,mrl_display,mrl_value,observed_at)"
            " VALUES(?,?,?,?,?,?)",
            (source, pesticide_en, commodity_ko, mrl.display(), mrl.value, ts))
        if prev is not None:
            conn.execute(
                "INSERT INTO change_events(detected_at,source,pesticide_en,commodity_ko,kind,old_value,new_value,note)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (ts, source, pesticide_en, commodity_ko, "MRL_CHANGED",
                 prev["mrl_display"], mrl.display(), "라이브 값 변경 관측"))
