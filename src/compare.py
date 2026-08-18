"""Deterministic 비교 엔진 (§3·§4·§5·§23) — 담당자 의사결정 중심.

핵심 질문(우선순위):
 1. 지침이 배포 중인 해외기준(RDA 외국 캐시)이 **현행 해외기준과 다른가?** → 지침 갱신 필요
 2. 그 성분이 수입국에서 **등록취소/사용금지로 바뀌었는가?** → 수출용 사용 불가
 3. eping상 **앞으로 바뀔 예정**인가? → N개월 후 대비
부가: 국내(한국) vs 현행 해외 = 수출 여유 참고(부차, INFO).

MRL 숫자/등록/날짜는 전부 deterministic code로 비교한다(LLM 미사용).
최신성 미확인은 '이상 없음'으로 표시하지 않는다(§22·§36).
"""
from __future__ import annotations

import math
from datetime import date, datetime

from . import db
from .masters import COMMODITIES, PESTICIDES
from .models import Confidence, Freshness, Health, Mrl, MrlKind, RegStatus, Severity
from .normalize import align_pipe, split_rda_product

# 수입국 소스 (지침 정합성 비교 대상). Codex는 국제 참조(부가).
IMPORT_SOURCES = [("EU", "EU"), ("Japan", "Japan")]


def _eq(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)


def confidence(health: str | None, freshness: str | None) -> Confidence:
    if health == Health.HEALTHY.value and freshness == Freshness.FRESH.value:
        return Confidence.HIGH
    if health in (Health.WARNING.value,) or freshness == Freshness.AGING.value:
        return Confidence.MEDIUM
    return Confidence.LOW


# ---- RDA 지침값 조회 ----

def rda_korea(conn, commodity_ko, pesticide_ko) -> Mrl | None:
    rows = conn.execute("SELECT product_name,korea_mrl FROM rda_guidelines WHERE commodity_ko=?",
                        (commodity_ko,)).fetchall()
    return _pick(rows, "korea_mrl", pesticide_ko)


def rda_published(conn, commodity_ko, pesticide_ko, target) -> Mrl | None:
    """RDA가 배포 중인 특정 수입국 외국 기준(캐시)."""
    rows = conn.execute(
        "SELECT product_name,foreign_cached_mrl FROM rda_guidelines "
        "WHERE target_country=? AND commodity_ko=?", (target, commodity_ko)).fetchall()
    return _pick(rows, "foreign_cached_mrl", pesticide_ko)


def _pick(rows, col, pesticide_ko) -> Mrl | None:
    best = None
    for row in rows:
        ingredients, _ = split_rda_product(row["product_name"])
        if pesticide_ko not in ingredients:
            continue
        val = align_pipe(row["product_name"], row[col]).get(pesticide_ko)
        single = len(ingredients) == 1
        if best is None or (single and not best[0]):
            best = (single, val)
    return best[1] if best else None


def live_mrl(conn, source, pesticide_en, commodity_ko) -> Mrl | None:
    r = conn.execute("SELECT mrl_kind,mrl_value,mrl_display,is_default FROM foreign_mrls "
                     "WHERE source=? AND pesticide_en=? AND commodity_ko=?",
                     (source, pesticide_en, commodity_ko)).fetchone()
    if not r:
        return None
    return Mrl(MrlKind(r["mrl_kind"]), value=r["mrl_value"], raw=r["mrl_display"],
               is_default=bool(r["is_default"]))


# ---- 1) 지침 정합성 판정 ----

def guideline_verdict(published: Mrl, live: Mrl) -> tuple[RegStatus, Severity, str]:
    """RDA 배포 해외기준(published) vs 현행 해외기준(live)."""
    if live.kind in (MrlKind.NOT_SET,):
        return (RegStatus.REVIEW_REQUIRED, Severity.HIGH,
                "현행에서 해당 기준 확인 안 됨 → 삭제/등록취소 여부 확인 필요")
    if published.kind == MrlKind.EXEMPT or live.kind == MrlKind.EXEMPT:
        if published.kind == live.kind:
            return RegStatus.MATCH, Severity.INFO, "지침=현행(면제)"
        return (RegStatus.FOREIGN_CHANGED, Severity.HIGH,
                f"면제 상태 변동: 지침 {published.display()} → 현행 {live.display()} · 지침 갱신 필요")
    if published.value is None or live.value is None:
        return RegStatus.AMBIGUOUS, Severity.MEDIUM, "수치 파싱 불가"
    if _eq(published.value, live.value):
        return RegStatus.MATCH, Severity.INFO, f"지침=현행 ({live.display()}) · 최신"
    stricter = live.value < published.value
    sev = Severity.CRITICAL if stricter else Severity.HIGH
    tail = (" · 현행이 더 엄격 → 지침대로 수출 시 초과 위반 위험! 즉시 갱신"
            if stricter else " · 지침 갱신 필요")
    return (RegStatus.FOREIGN_CHANGED, sev,
            f"지침 배포값 {published.display()} → 현행 {live.display()}{tail}")


# ---- 2) 등록상태(수출 가부) ----

def registration(conn, source, pesticide_en):
    return conn.execute(
        "SELECT status,expiry_date FROM registrations WHERE source=? AND pesticide_en=?",
        (source, pesticide_en)).fetchone()


# ---- 3) eping 변경예고 매칭 ----

def _months_until(d: str | None) -> int | None:
    if not d:
        return None
    try:
        dt = datetime.strptime(d[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return max(0, (dt.year - date.today().year) * 12 + (dt.month - date.today().month))


def upcoming_from_eping(conn) -> list[dict]:
    """SPS 통보문 중 master 성분이 언급되고 시행예정일이 미래인 것 → 변경예고."""
    out = []
    rows = conn.execute(
        "SELECT member,document_symbol,title,products,entry_into_force,comment_deadline,link "
        "FROM sps_notifications").fetchall()
    ens = {pm["english"].lower(): (ko, pm) for ko, pm in PESTICIDES.items()}
    for r in rows:
        text = f"{r['title'] or ''} {r['products'] or ''}".lower()
        hit_en = next((en for en in ens if en in text), None)
        if not hit_en:
            continue
        months = _months_until(r["entry_into_force"])
        ko, _ = ens[hit_en]
        when = (r["entry_into_force"] or r["comment_deadline"] or "")[:10]
        if months is not None:
            tail = f" · 약 {months}개월 후({when}) 시행 예정"
        elif when:
            tail = f" · 의견마감/시행 {when}"
        else:
            tail = " · 시행일 미정"
        note = f"{r['member']} {r['document_symbol']}: {ko}({hit_en}) 관련 기준 변경 예고{tail}"
        out.append({"member": r["member"], "symbol": r["document_symbol"],
                    "pesticide_ko": ko, "pesticide_en": hit_en, "months": months,
                    "when": when, "title": r["title"], "link": r["link"], "note": note})
        db.add_alert(conn, category="UPCOMING",
                     severity=("HIGH" if (months is not None and months <= 6) else "MEDIUM"),
                     title=f"[예고] {ko} 기준 변경 예정 ({r['member']})", body=note, source="WTO")
    return out


# ---- 메인 ----

def run_comparisons(conn) -> dict:
    run_at = db.now_iso()
    conn.execute("DELETE FROM comparison_results")
    health = {r["source"]: r for r in conn.execute("SELECT * FROM source_health").fetchall()}
    rows: list[dict] = []

    def _emit(source, commodity_ko, pest_ko, pest_en, item, status, sev, korea, foreign, detail):
        h = health.get(source)
        hstatus = h["status"] if h else Health.UNKNOWN.value
        hfresh = h["freshness"] if h else Freshness.UNKNOWN.value
        conf = confidence(hstatus, hfresh)
        r = dict(source=source, pesticide_ko=pest_ko, pesticide_en=pest_en, commodity_ko=commodity_ko,
                 item=item, status=status.value, severity=sev.value,
                 korea_mrl=(korea.display() if korea else None),
                 foreign_mrl=foreign, detail=detail, data_confidence=conf.value,
                 source_status=hstatus, source_freshness=hfresh,
                 last_success_at=(h["last_success_at"] if h else None),
                 data_date=(h["last_data_date"] if h else None))
        conn.execute(
            "INSERT INTO comparison_results(run_at,source,pesticide_ko,pesticide_en,commodity_ko,"
            "item,status,severity,korea_mrl,foreign_mrl,detail,data_confidence,source_status,"
            "source_freshness,last_success_at,data_date) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_at, r["source"], r["pesticide_ko"], r["pesticide_en"], r["commodity_ko"], r["item"],
             r["status"], r["severity"], r["korea_mrl"], r["foreign_mrl"], r["detail"],
             r["data_confidence"], r["source_status"], r["source_freshness"],
             r["last_success_at"], r["data_date"]))
        rows.append(r)

    for commodity_ko in COMMODITIES:
        for pest_ko, pm in PESTICIDES.items():
            en = pm["english"]
            korea = rda_korea(conn, commodity_ko, pest_ko)

            for source, target in IMPORT_SOURCES:
                published = rda_published(conn, commodity_ko, pest_ko, target)
                if published is None:
                    continue  # 지침에 없는 (성분×작물×국가)는 비교대상 아님(수출조합만 수록)
                live = live_mrl(conn, source, en, commodity_ko)
                h = health.get(source)
                hstatus = h["status"] if h else Health.UNKNOWN.value
                healthy = hstatus in (Health.HEALTHY.value, Health.WARNING.value)

                # (1) 지침 정합성
                if live is None and not healthy:
                    status, sev = RegStatus.REVIEW_REQUIRED, Severity.HIGH
                    detail = (f"{source} 라이브 수집 실패 → 지침 배포값 {published.display()}의 "
                              f"최신성 확인 불가(신뢰 불가). 담당자 확인 필요")
                    foreign = f"{published.display()}(지침 캐시)"
                elif live is None and healthy:
                    status, sev = RegStatus.REVIEW_REQUIRED, Severity.HIGH
                    detail = (f"현행 {source}에서 {en}/{commodity_ko} 기준 미확인 "
                              f"(지침 배포값 {published.display()}) → 삭제/등록취소 확인 필요")
                    foreign = None
                else:
                    status, sev, detail = guideline_verdict(published, live)
                    foreign = live.display()
                _emit(source, commodity_ko, pest_ko, en, "GUIDELINE", status, sev, korea, foreign, detail)

                if status == RegStatus.FOREIGN_CHANGED:
                    db.add_alert(conn, category="REGULATION", severity=sev.value,
                                 title=f"[지침갱신] {source} {commodity_ko}/{en}", body=detail, source=source)

                # (부가) 국내 vs 현행 = 수출 여유 참고
                if live is not None and korea is not None and \
                        korea.kind == MrlKind.NORMAL and live.kind == MrlKind.NORMAL and \
                        korea.value is not None and live.value is not None and korea.value > live.value:
                    _emit(source, commodity_ko, pest_ko, en, "EXPORT_MARGIN",
                          RegStatus.RDA_HIGHER, Severity.MEDIUM, korea, live.display(),
                          f"참고: 국내 지침 {korea.display()} > 현행 {live.display()} — 국내 등록량으로 수출 시 초과 주의")

            # (2) 등록상태(EU) — 수출 가부
            reg = registration(conn, "EU", en)
            published_eu = rda_published(conn, commodity_ko, pest_ko, "EU")
            if reg and published_eu is not None and (reg["status"] or "").lower().startswith("not"):
                _emit("EU", commodity_ko, pest_ko, en, "REGISTRATION",
                      RegStatus.REGISTRATION_CHANGED, Severity.CRITICAL, korea,
                      f"등록: {reg['status']}",
                      f"⚠ EU에서 {en} 미승인(Not approved, 만료 {reg['expiry_date']}). "
                      f"지침은 아직 {commodity_ko}에 배포 중 → EU 수출용 사용 불가로 갱신 필요")
                db.add_alert(conn, category="REGISTRATION", severity="CRITICAL",
                             title=f"[수출불가] EU {commodity_ko}/{en} 미승인",
                             body=f"{en} EU 미승인(만료 {reg['expiry_date']}). 지침에서 제외 검토 필요.", source="EU")

    upcoming = upcoming_from_eping(conn)
    conn.commit()
    return {"comparisons": rows, "upcoming": upcoming}
