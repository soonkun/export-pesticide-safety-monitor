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
from .masters import COMMODITIES, PESTICIDES, member_label
from .models import Confidence, Freshness, Health, Mrl, MrlKind, RegStatus, Severity
from .normalize import align_pipe, split_rda_product

# 지침 원문의 국가명 → 우리가 현행 기준을 수집하는 소스.
# 지침은 13개국을 배포하지만 현행 기준을 자동 수집할 수 있는 곳은 아직 이 둘뿐이다.
COUNTRY_SOURCE = {"EU": "EU", "일본": "Japan", "미국": "USA", "대만": "Taiwan"}
IMPORT_SOURCES = [(src, country) for country, src in COUNTRY_SOURCE.items()]


def commodity_mapped(source: str, commodity_ko: str) -> bool:
    """그 소스에서 이 작목을 조회할 식별자가 마스터에 있는가."""
    cm = COMMODITIES.get(commodity_ko)
    if not cm:
        return False
    key = {"Japan": "japan_name", "USA": "usa_name",
           "Taiwan": "taiwan_name"}.get(source, "eu_product_id")
    return bool(cm.get(key))


def coverage(conn) -> dict:
    """지침이 배포 중인 (국가×작목) 조합 중 현행과 대조 가능한 것이 얼마인지.

    대조 못 하는 조합을 화면에서 지우면 "이상 없음"으로 오해된다. 건수와 사유를 남긴다.
    """
    rows = conn.execute(
        "SELECT target_country, commodity_ko, COUNT(*) AS n FROM rda_guidelines "
        "GROUP BY 1,2 ORDER BY n DESC").fetchall()
    covered, no_source, no_mapping = [], [], []
    for r in rows:
        item = {"country": r["target_country"], "commodity": r["commodity_ko"], "rows": r["n"]}
        src = COUNTRY_SOURCE.get(r["target_country"])
        if not src:
            no_source.append(item)
        elif not commodity_mapped(src, r["commodity_ko"]):
            no_mapping.append(item)
        else:
            covered.append(item)
    return {"covered": covered, "no_source": no_source, "no_mapping": no_mapping,
            "total": len(rows)}


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


def live_row(conn, source, pesticide_en, commodity_ko):
    """현행 해외기준 1건 → (Mrl, 근거 dict). 없으면 (None, {})."""
    r = conn.execute("SELECT mrl_kind,mrl_value,mrl_display,is_default,note,source_url,basis "
                     "FROM foreign_mrls WHERE source=? AND pesticide_en=? AND commodity_ko=?",
                     (source, pesticide_en, commodity_ko)).fetchone()
    if not r:
        return None, {}
    mrl = Mrl(MrlKind(r["mrl_kind"]), value=r["mrl_value"], raw=r["mrl_display"],
              note=r["note"] or "", is_default=bool(r["is_default"]))
    hist = conn.execute(
        "SELECT observed_at FROM mrl_history WHERE source=? AND pesticide_en=? AND commodity_ko=? "
        "ORDER BY id", (source, pesticide_en, commodity_ko)).fetchall()
    # 이력이 1건이면 '처음 확인한 날', 2건 이상이면 '값이 바뀐 걸 감지한 날'
    when = (hist[-1]["observed_at"] or "")[:10] if hist else ""
    changed_at = (f"{when} 변경 감지" if len(hist) > 1 else (f"{when} 최초 확인" if when else ""))
    return mrl, {"source_url": r["source_url"], "basis": r["basis"], "changed_at": changed_at}


def live_mrl(conn, source, pesticide_en, commodity_ko) -> Mrl | None:
    return live_row(conn, source, pesticide_en, commodity_ko)[0]


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


# ---- 3) eping 통보문 분류 (§3) ----
# 원칙: "이미 시행됐고 우리 수집에 반영됐다"는 알릴 이유가 없다. 알릴 것은 두 가지뿐이다.
#   ① 시행됐는데 우리 데이터가 그 이후로 갱신되지 않음 → 미반영 의심, 즉시 수정 (근거자료 첨부)
#   ② 아직 시행 전 → D-day 와 함께 대비
# 나머지(반영 확인 / 우리가 기준을 수집하지 않는 회원국의 지난 통보)는 숨기고 건수만 남긴다.

# 우리가 현행 MRL 을 직접 수집하는 회원국 → 반영 여부를 판정할 수 있다.
TRACKED_MEMBERS = {"European Union": "EU", "Japan": "Japan",
                   "United States of America": "USA"}


def _days_until(d: str | None) -> int | None:
    if not d:
        return None
    try:
        return (datetime.strptime(d[:10], "%Y-%m-%d").date() - date.today()).days
    except ValueError:
        return None


def dday(days: int | None) -> str:
    if days is None:
        return "D-?"
    if days == 0:
        return "D-DAY"
    return f"D-{days}" if days > 0 else f"D+{-days}"


def _upcoming_severity(days: int | None) -> str:
    if days is None or days > 90:
        return "LOW"
    return "HIGH" if days <= 30 else "MEDIUM"


def classify_eping(conn) -> dict:
    """SPS 통보문 중 master 성분이 언급된 것을 미반영/대비/숨김으로 분류한다(읽기 전용).

    보고서도 같은 함수를 그대로 호출한다 — 알림과 화면이 갈라지지 않도록.
    """
    last_ok = {r["source"]: r["last_success_at"]
               for r in conn.execute("SELECT source,last_success_at FROM source_health")}
    ens = {pm["english"].lower(): ko for ko, pm in PESTICIDES.items()}

    urgent, prepare = [], []
    hidden = {"reflected": 0, "out_of_scope": 0, "undated": 0}
    rows = conn.execute(
        "SELECT member,document_symbol,title,products,entry_into_force,comment_deadline,link "
        "FROM sps_notifications").fetchall()
    for r in rows:
        text = f"{r['title'] or ''} {r['products'] or ''}".lower()
        hit_en = next((en for en in ens if en in text), None)
        if not hit_en:
            continue
        ko = ens[hit_en]
        member = r["member"]
        source = TRACKED_MEMBERS.get(member)
        eif = (r["entry_into_force"] or "")[:10]
        days = _days_until(eif)
        base = {"member": member, "symbol": r["document_symbol"], "pesticide_ko": ko,
                "pesticide_en": hit_en, "title": r["title"], "link": r["link"],
                "entry_into_force": eif, "comment_deadline": (r["comment_deadline"] or "")[:10]}

        if days is None:                      # 시행일 미정 → 의견마감이 남았으면 대비, 아니면 숨김
            cd_days = _days_until(r["comment_deadline"])
            if cd_days is not None and cd_days >= 0:
                prepare.append({**base, "days": cd_days, "when": base["comment_deadline"],
                                "basis": "의견마감"})
            else:
                hidden["undated"] += 1
            continue

        if days > 0:                          # 아직 도래하지 않음 → 대비
            prepare.append({**base, "days": days, "when": eif, "basis": "시행"})
            continue

        # 이미 시행됨
        if source is None:                    # 우리가 그 나라 기준을 수집하지 않음 → 판정 불가, 숨김
            hidden["out_of_scope"] += 1
            continue
        collected = (last_ok.get(source) or "")[:10]
        if collected and collected >= eif:    # 발효 이후에 정상 수집 → 현행값에 이미 반영됨
            hidden["reflected"] += 1
            continue
        urgent.append({**base, "days": days, "when": eif, "source": source,
                       "last_success": collected or "없음"})

    prepare.sort(key=lambda x: x["days"])
    urgent.sort(key=lambda x: x["days"])

    return {"urgent": urgent, "prepare": prepare, "hidden": hidden}


def eping_evidence(conn, source: str, pesticide_en: str) -> str | None:
    """지침≠현행으로 판정된 건에 대해 '왜·언제 바뀌었는지' 근거가 될 SPS 통보문을 찾는다.

    같은 회원국이 그 성분으로 낸 통보문 중 가장 최근 것 1건 → '문서번호|시행일|링크'.
    없으면 None (근거 없음을 근거 있음처럼 꾸미지 않는다).
    """
    member = next((m for m, s in TRACKED_MEMBERS.items() if s == source), None)
    if not member:
        return None
    r = conn.execute(
        "SELECT document_symbol,entry_into_force,distribution_date,link,title "
        "FROM sps_notifications WHERE member=? AND (lower(title) LIKE ? OR lower(products) LIKE ?) "
        "ORDER BY COALESCE(entry_into_force, distribution_date) DESC LIMIT 1",
        (member, f"%{pesticide_en.lower()}%", f"%{pesticide_en.lower()}%")).fetchone()
    if not r:
        return None
    when = (r["entry_into_force"] or r["distribution_date"] or "")[:10]
    return "|".join([r["document_symbol"] or "", when, r["link"] or "", (r["title"] or "")[:120]])


def emit_eping_alerts(conn, eping: dict) -> None:
    """분류 결과를 알림으로 발행. 숨김 대상은 알림도 만들지 않는다."""
    urgent, prepare = eping["urgent"], eping["prepare"]
    for u in urgent:
        db.add_alert(
            conn, category="UNREFLECTED", severity="CRITICAL",
            title=f"[미반영] {member_label(u['member'])} {u['pesticide_ko']} 기준 변경 시행 — 즉시 확인",
            body=(f"{u['entry_into_force']} 시행({dday(u['days'])})된 변경이 우리 데이터에 반영됐다는 근거가 없습니다.\n"
                  f"근거자료: {u['symbol']} · {u['title']}\n{u['link']}\n"
                  f"{u['source']} 마지막 정상수집 {u['last_success']} < 발효일 {u['entry_into_force']}\n"
                  f"→ {u['source']} 수집을 즉시 재실행하고, 지침 배포값을 현행과 대조하십시오."),
            source="WTO")
    for p in prepare:
        db.add_alert(
            conn, category="UPCOMING", severity=_upcoming_severity(p["days"]),
            title=f"[대비 {dday(p['days'])}] {member_label(p['member'])} {p['pesticide_ko']} 기준 변경 {p['basis']} 예정",
            body=(f"{p['when']} {p['basis']} ({dday(p['days'])})\n"
                  f"근거자료: {p['symbol']} · {p['title']}\n{p['link']}"),
            source="WTO")


# ---- 메인 ----

def run_comparisons(conn) -> dict:
    run_at = db.now_iso()
    conn.execute("DELETE FROM comparison_results")
    health = {r["source"]: r for r in conn.execute("SELECT * FROM source_health").fetchall()}
    rows: list[dict] = []

    def _emit(source, commodity_ko, pest_ko, pest_en, item, status, sev, korea, foreign, detail,
                  published=None, ev=None):
        ev = ev or {}
        h = health.get(source)
        hstatus = h["status"] if h else Health.UNKNOWN.value
        hfresh = h["freshness"] if h else Freshness.UNKNOWN.value
        conf = confidence(hstatus, hfresh)
        r = dict(source=source, pesticide_ko=pest_ko, pesticide_en=pest_en, commodity_ko=commodity_ko,
                 item=item, status=status.value, severity=sev.value,
                 korea_mrl=(korea.display() if korea else None),
                 published_mrl=(published.display() if published else None),
                 foreign_mrl=foreign, detail=detail, data_confidence=conf.value,
                 source_url=ev.get("source_url"), basis=ev.get("basis"),
                 changed_at=ev.get("changed_at"), evidence=ev.get("evidence"),
                 source_status=hstatus, source_freshness=hfresh,
                 last_success_at=(h["last_success_at"] if h else None),
                 data_date=(h["last_data_date"] if h else None))
        # 컬럼 목록을 dict 에서 만든다 — 필드가 늘 때마다 ?의 개수를 세지 않도록.
        cols = ["run_at", *r]
        conn.execute(f"INSERT INTO comparison_results({','.join(cols)})"
                     f" VALUES({','.join('?' * len(cols))})", [run_at, *r.values()])
        rows.append(r)

    for commodity_ko in COMMODITIES:
        for pest_ko, pm in PESTICIDES.items():
            en = pm["english"]
            korea = rda_korea(conn, commodity_ko, pest_ko)

            for source, target in IMPORT_SOURCES:
                published = rda_published(conn, commodity_ko, pest_ko, target)
                if published is None:
                    continue  # 지침에 없는 (성분×작물×국가)는 비교대상 아님(수출조합만 수록)
                if not commodity_mapped(source, commodity_ko):
                    # 그 소스에서 이 작목을 조회할 식별자가 아직 없다.
                    # 여기서 비교하면 "수입국이 기준을 삭제했다"로 잘못 보고된다.
                    # 미대조 사실은 coverage() 의 '작목 매핑 확인 필요'로 이미 집계된다.
                    continue
                live, ev = live_row(conn, source, en, commodity_ko)
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
                    if live.note:
                        detail += f" · {live.note}"
                    foreign = live.display()
                if status == RegStatus.FOREIGN_CHANGED:
                    ev = {**ev, "evidence": eping_evidence(conn, source, en)}
                _emit(source, commodity_ko, pest_ko, en, "GUIDELINE", status, sev, korea, foreign, detail,
                      published=published, ev=ev)

                if status == RegStatus.FOREIGN_CHANGED:
                    db.add_alert(conn, category="REGULATION", severity=sev.value,
                                 title=f"[지침갱신] {member_label(source)} {commodity_ko}/{pest_ko}",
                                 body=detail, source=source)

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
                             title=f"[수출불가] {member_label('EU')} {commodity_ko}/{pest_ko} 미승인",
                             body=f"{en} EU 미승인(만료 {reg['expiry_date']}). 지침에서 제외 검토 필요.", source="EU")

    eping = classify_eping(conn)
    emit_eping_alerts(conn, eping)
    conn.commit()
    return {"comparisons": rows, "eping": eping}
