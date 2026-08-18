"""Collector 베이스: 재시도·검증·스냅샷·헬스·freshness 공통 처리 (§19·§21·§29).

각 소스 collector는 collect(conn, session)만 구현하면 되고,
성공/실패 판정, 재시도, collection_runs/source_health 기록, 알림은 base가 담당한다.
"""
from __future__ import annotations

import hashlib
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime

from .. import db
from ..config import SOURCES
from ..http import AuthError, ParserError, SchemaChanged, SourceUnavailable, session
from ..models import Freshness, Health

# 재시도 지연(초). 운영 권장은 5분·30분(§29)이나 PoC는 짧게. RETRY_DELAYS로 조정.
RETRY_DELAYS = [0, 2, 5]

COLLECTOR_VERSION = "0.1.0"


@dataclass
class CollectResult:
    """collect()가 돌려주는 수집 결과 요약."""
    http_status: int | None = None
    records_received: int = 0
    records_valid: int = 0
    records_invalid: int = 0
    schema_hash: str | None = None
    content_hash: str | None = None
    data_date: str | None = None          # 소스가 알려주는 데이터 기준일
    warnings: list[str] = field(default_factory=list)   # 이상치 등 → WARNING 유발


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()[:16]


class BaseCollector:
    name: str = "BASE"
    parser_version: str = "0.1.0"

    def collect(self, conn, s) -> CollectResult:  # pragma: no cover - overridden
        raise NotImplementedError

    # ---- 오케스트레이션 ----
    def run(self, conn) -> dict:
        started = db.now_iso()
        t0 = time.time()
        s = session()
        result: CollectResult | None = None
        status = Health.UNKNOWN
        error_type = error_msg = None
        retry = 0

        for attempt, delay in enumerate(RETRY_DELAYS):
            if delay:
                time.sleep(delay)
            try:
                result = self.collect(conn, s)
                status = Health.HEALTHY
                if result.warnings:
                    status = Health.WARNING
                break
            except AuthError as e:
                status, error_type, error_msg = Health.AUTH_ERROR, "AuthError", str(e)
                break  # 재시도 무의미(§29)
            except SchemaChanged as e:
                status, error_type, error_msg = Health.SCHEMA_CHANGED, "SchemaChanged", str(e)
                break
            except ParserError as e:
                status, error_type, error_msg = Health.PARSER_ERROR, "ParserError", str(e)
                break
            except SourceUnavailable as e:
                status, error_type, error_msg = Health.SOURCE_UNAVAILABLE, "SourceUnavailable", str(e)
                retry = attempt
            except Exception as e:  # 네트워크/기타 → 재시도
                status, error_type, error_msg = Health.FAILED, type(e).__name__, str(e)
                error_msg = (error_msg or "") + " | " + traceback.format_exc().splitlines()[-1]
                retry = attempt
        finished = db.now_iso()
        rt = round(time.time() - t0, 2)

        ok = status in (Health.HEALTHY, Health.WARNING)
        prev = conn.execute("SELECT last_success_at,consecutive_failures FROM source_health WHERE source=?",
                            (self.name,)).fetchone()
        consec = 0 if ok else ((prev["consecutive_failures"] if prev else 0) + 1)
        last_success = finished if ok else (prev["last_success_at"] if prev else None)

        # freshness (§21)
        fresh = self._freshness(last_success, result.data_date if result else None)

        db.add_run(conn, source=self.name, started_at=started, finished_at=finished,
                   status=status.value, http_status=(result.http_status if result else None),
                   records_received=(result.records_received if result else 0),
                   records_valid=(result.records_valid if result else 0),
                   records_invalid=(result.records_invalid if result else 0),
                   schema_changed=int(status == Health.SCHEMA_CHANGED),
                   error_type=error_type, error_message=error_msg, retry_count=retry)

        health_kw = dict(
            latest_attempt_at=finished,
            last_success_at=last_success,
            last_data_date=(result.data_date if result and result.data_date else None),
            expected_update_interval=SOURCES[self.name]["interval_days"],
            consecutive_failures=consec,
            http_status=(result.http_status if result else None),
            response_time=rt,
            number_of_records=(result.records_received if result else 0),
            schema_hash=(result.schema_hash if result else None),
            content_hash=(result.content_hash if result else None),
            collector_version=COLLECTOR_VERSION, parser_version=self.parser_version,
            status=status.value,
            status_message=error_msg or (",".join(result.warnings) if result else ""),
            freshness=fresh.value,
        )
        if not ok:
            health_kw["last_failure_at"] = finished
        db.upsert_health(conn, self.name, **health_kw)

        # 시스템 알림 (§26) — 실패/스키마변경은 알림 대상
        if not ok:
            db.add_alert(conn, category="SYSTEM", severity=("HIGH" if consec >= 1 else "MEDIUM"),
                         title=f"[{self.name}] 데이터 수집 {status.value}",
                         body=f"{error_type}: {error_msg}\n연속 실패: {consec}회\n"
                              f"마지막 정상 수집: {last_success or '없음'}\n"
                              f"→ 현재 {self.name} 관련 비교결과의 최신성을 보장할 수 없음. 담당자 확인 필요.",
                         source=self.name)
        conn.commit()
        return {"source": self.name, "status": status.value, "freshness": fresh.value,
                "records": (result.records_received if result else 0),
                "response_time": rt, "error": error_msg}

    def _freshness(self, last_success: str | None, data_date: str | None) -> Freshness:
        if not last_success:
            return Freshness.UNKNOWN
        interval = SOURCES[self.name]["interval_days"]
        try:
            ls = datetime.fromisoformat(last_success)
        except ValueError:
            return Freshness.UNKNOWN
        age_days = (datetime.now(ls.tzinfo) - ls).total_seconds() / 86400
        if age_days <= interval:
            return Freshness.FRESH
        if age_days <= interval * 2:
            return Freshness.AGING
        return Freshness.STALE
