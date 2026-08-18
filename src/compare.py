"""Deterministic 비교 엔진 (§3·§4·§5·§23).

MRL 숫자/면제/기본값은 코드로만 비교한다. LLM 미사용.
- 국내(한국) vs 해외 라이브 → MATCH / RDA_STRICTER / RDA_HIGHER / NO_FOREIGN_STANDARD ...
- RDA 캐시(외국) vs 해외 라이브 → 다르면 FOREIGN_CHANGED (지침 최신성 문제)
- 각 결과에 Source 상태·Freshness·Data confidence 병기(§23·§36). 최신성 미확인은 안심시키지 않음.
"""
from __future__ import annotations

import math

from . import db
from .masters import COMMODITIES, PESTICIDES
from .models import Confidence, Freshness, Health, Mrl, MrlKind, RegStatus, Severity
from .normalize import align_pipe, split_rda_product

# 소스 → (RDA 캐시 대상국 라벨 or None)
SOURCE_RDA_TARGET = {"EU": "EU", "Japan": "Japan", "Codex": None}


def _eq(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)


def compare_mrl(korea: Mrl | None, foreign: Mrl | None) -> tuple[RegStatus, Severity, str]:
    if foreign is None or foreign.kind in (MrlKind.NOT_SET,):
        return RegStatus.NO_FOREIGN_STANDARD, Severity.INFO, "해외 기준 없음"
    if foreign.kind == MrlKind.LOQ_DEFAULT:
        return RegStatus.NO_FOREIGN_STANDARD, Severity.INFO, "해외 기본값/LOQ(특정 MRL 미설정)"
    if korea is None or korea.kind == MrlKind.NOT_SET:
        return RegStatus.REVIEW_REQUIRED, Severity.MEDIUM, "국내 지침값 없음/미매핑"
    if korea.kind == MrlKind.EXEMPT and foreign.kind == MrlKind.EXEMPT:
        return RegStatus.MATCH, Severity.INFO, "양측 면제"
    if (korea.kind == MrlKind.EXEMPT) != (foreign.kind == MrlKind.EXEMPT):
        return RegStatus.REVIEW_REQUIRED, Severity.MEDIUM, "한쪽만 면제"
    if korea.value is None or foreign.value is None:
        return RegStatus.AMBIGUOUS, Severity.MEDIUM, "수치 파싱 불가"
    if _eq(korea.value, foreign.value):
        return RegStatus.MATCH, Severity.INFO, "동일"
    if korea.value < foreign.value:
        return RegStatus.RDA_STRICTER, Severity.LOW, f"국내 {korea.display()} < 해외 {foreign.display()}"
    return RegStatus.RDA_HIGHER, Severity.HIGH, f"국내 {korea.display()} > 해외 {foreign.display()} (수출 리스크)"


def confidence(health: str | None, freshness: str | None) -> Confidence:
    if health == Health.HEALTHY.value and freshness == Freshness.FRESH.value:
        return Confidence.HIGH
    if health in (Health.WARNING.value,) or freshness == Freshness.AGING.value:
        return Confidence.MEDIUM
    return Confidence.LOW


def rda_korea(conn, commodity_ko: str, pesticide_ko: str) -> Mrl | None:
    """국내(한국) MRL — 국가 무관이므로 모든 대상국 행에서 조회(단일성분 우선)."""
    rows = conn.execute(
        "SELECT product_name,korea_mrl FROM rda_guidelines WHERE commodity_ko=?",
        (commodity_ko,)).fetchall()
    best = None
    for row in rows:
        ingredients, _ = split_rda_product(row["product_name"])
        if pesticide_ko not in ingredients:
            continue
        val = align_pipe(row["product_name"], row["korea_mrl"]).get(pesticide_ko)
        single = len(ingredients) == 1
        if best is None or (single and not best[0]):
            best = (single, val)
    return best[1] if best else None


def rda_cached(conn, commodity_ko: str, pesticide_ko: str, target_country: str) -> Mrl | None:
    """RDA가 캐시한 특정 수입국의 외국 MRL(단일성분 우선)."""
    rows = conn.execute(
        "SELECT product_name,foreign_cached_mrl FROM rda_guidelines "
        "WHERE target_country=? AND commodity_ko=?", (target_country, commodity_ko)).fetchall()
    best = None
    for row in rows:
        ingredients, _ = split_rda_product(row["product_name"])
        if pesticide_ko not in ingredients:
            continue
        val = align_pipe(row["product_name"], row["foreign_cached_mrl"]).get(pesticide_ko)
        single = len(ingredients) == 1
        if best is None or (single and not best[0]):
            best = (single, val)
    return best[1] if best else None


def run_comparisons(conn) -> list[dict]:
    run_at = db.now_iso()
    conn.execute("DELETE FROM comparison_results")
    health_rows = {r["source"]: r for r in conn.execute("SELECT * FROM source_health").fetchall()}
    results: list[dict] = []

    for commodity_ko in COMMODITIES:
        for pesticide_ko, pm in PESTICIDES.items():
            en = pm["english"]
            korea = rda_korea(conn, commodity_ko, pesticide_ko)
            for source in ("EU", "Japan", "Codex"):
                target = SOURCE_RDA_TARGET[source]
                cached = rda_cached(conn, commodity_ko, pesticide_ko, target) if target else None

                # RDA 지침에 없는 (성분×작물)은 비교대상 아님(수출조합만 수록, STEP4). 스킵.
                if korea is None and cached is None:
                    continue

                live = _live_mrl(conn, source, en, commodity_ko)
                h = health_rows.get(source)
                hstatus = h["status"] if h else Health.UNKNOWN.value
                hfresh = h["freshness"] if h else Freshness.UNKNOWN.value
                last_ok = h["last_success_at"] if h else None
                data_date = h["last_data_date"] if h else None

                # 라이브가 없고 소스가 건강하지 않으면: Fail-safe(§22) — 캐시를 최신처럼 쓰지 않음
                foreign_for_compare = live
                detail_extra = ""
                if live is None and hstatus not in (Health.HEALTHY.value, Health.WARNING.value):
                    if cached is not None:
                        foreign_for_compare = None  # 비교는 보류
                        detail_extra = (f" · 라이브 수집 실패 → RDA 캐시({cached.display()})는 "
                                        f"최신성 미확인, 신뢰 불가")

                # RDA와 무관하게 매핑 자체가 없으면 스킵(비교대상 아님)
                if korea is None and live is None and cached is None:
                    continue

                if foreign_for_compare is None and live is None and hstatus not in (
                        Health.HEALTHY.value, Health.WARNING.value):
                    status, sev, detail = RegStatus.REVIEW_REQUIRED, Severity.HIGH, \
                        f"{source} 최신성 확인 필요{detail_extra}"
                else:
                    status, sev, detail = compare_mrl(korea, foreign_for_compare)

                # RDA 캐시 vs 라이브 변경 탐지 (지침 최신성)
                if cached is not None and live is not None and \
                        cached.kind == MrlKind.NORMAL and live.kind == MrlKind.NORMAL and \
                        cached.value is not None and live.value is not None and \
                        not _eq(cached.value, live.value):
                    status = RegStatus.FOREIGN_CHANGED
                    sev = Severity.HIGH
                    detail = f"RDA 캐시 {cached.display()} ≠ {source} 라이브 {live.display()} → 지침 갱신 필요"
                    db.add_alert(conn, category="REGULATION", severity=sev.value,
                                 title=f"[{source}] {commodity_ko}/{en} 해외 MRL 변경 탐지",
                                 body=detail, source=source)

                conf = confidence(hstatus, hfresh)
                if status == RegStatus.RDA_HIGHER:
                    db.add_alert(conn, category="REGULATION", severity=sev.value,
                                 title=f"[{source}] {commodity_ko}/{en} 국내 MRL이 해외보다 높음",
                                 body=detail, source=source)

                row = dict(source=source, pesticide_ko=pesticide_ko, pesticide_en=en,
                           commodity_ko=commodity_ko, item="MRL", status=status.value,
                           severity=sev.value,
                           korea_mrl=(korea.display() if korea else None),
                           foreign_mrl=(live.display() if live else (cached.display() + "(캐시)" if cached else None)),
                           detail=detail, data_confidence=conf.value, source_status=hstatus,
                           source_freshness=hfresh, last_success_at=last_ok, data_date=data_date)
                conn.execute(
                    "INSERT INTO comparison_results(run_at,source,pesticide_ko,pesticide_en,"
                    "commodity_ko,item,status,severity,korea_mrl,foreign_mrl,detail,"
                    "data_confidence,source_status,source_freshness,last_success_at,data_date)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (run_at, *[row[k] for k in ("source", "pesticide_ko", "pesticide_en",
                     "commodity_ko", "item", "status", "severity", "korea_mrl", "foreign_mrl",
                     "detail", "data_confidence", "source_status", "source_freshness",
                     "last_success_at", "data_date")]))
                results.append(row)
    conn.commit()
    return results


def _live_mrl(conn, source, pesticide_en, commodity_ko) -> Mrl | None:
    r = conn.execute(
        "SELECT mrl_kind,mrl_value,mrl_display,is_default FROM foreign_mrls "
        "WHERE source=? AND pesticide_en=? AND commodity_ko=?",
        (source, pesticide_en, commodity_ko)).fetchone()
    if not r:
        return None
    return Mrl(MrlKind(r["mrl_kind"]), value=r["mrl_value"], raw=r["mrl_display"],
               is_default=bool(r["is_default"]))
