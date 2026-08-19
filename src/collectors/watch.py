"""개정 감시 collector — 값을 기계 판독할 수 없는 기준을 '개정 여부'로 추적한다.

문서를 한 번 내려받는 것은 스냅샷이지 모니터링이 아니다. 중국 GB 2763 은 스캔 PDF 라
MRL 숫자를 읽을 수 없고, 호주 Schedule 20 은 문서 다운로드 경로를 못 찾았다. 그렇다고
"확인 불가"로 비워두면, 정작 **기준이 개정된 순간**을 놓친다.

두 나라 모두 값은 못 읽어도 **현행판이 무엇이고 언제 바뀌었는지**는 공개 API 로 매일 확인된다.
담당자에게 필요한 건 10,092개 숫자가 아니라 "지금 들여다봐야 하는가" 이므로, 판 번호·시행일이
바뀌면 알림을 띄운다. 값 대조는 여전히 불가하며 그 사실은 커버리지에 그대로 남는다.
"""
from __future__ import annotations

from .. import db
import re

from ..config import (AU_SCHEDULE20_TITLE, AU_VERSIONS_URL, CN_SEARCH_URL, CN_SOURCE_PAGE,
                      SG_REG30_URL)
from ..http import ParserError, SourceUnavailable
from .base import BaseCollector, CollectResult, sha


class StandardWatchCollector(BaseCollector):
    """현행 기준의 판 정보만 수집한다. foreign_mrls 는 만들지 않는다."""

    def current_standards(self, s) -> list[dict]:   # pragma: no cover - overridden
        raise NotImplementedError

    def collect(self, conn, s) -> CollectResult:
        stds = self.current_standards(s)
        if not stds:
            raise ParserError(f"{self.name}: 현행 기준 판 정보를 얻지 못함")

        # 이 소스를 한 번이라도 본 적이 있는가. 최초 실행이면 지금 보이는 판이 기준선이고,
        # 그 뒤에 **처음 나타나는 판**은 곧 개정이다 — 이걸 놓치면 감시하는 의미가 없다.
        seen_before = conn.execute(
            "SELECT COUNT(*) FROM standard_watch WHERE source=?", (self.name,)).fetchone()[0] > 0
        known = {r["standard_code"] for r in conn.execute(
            "SELECT standard_code FROM standard_watch WHERE source=?", (self.name,))}

        changes = []
        for std in stds:
            is_new = std["code"] not in known
            changed = db.record_standard(conn, source=self.name, **std)
            if is_new and seen_before:
                changed = (f"신규 판 등장: {std['code']} "
                           f"(발표 {std.get('published')} · 시행 {std.get('effective')})")
            if changed:
                changes.append(changed)
                db.add_alert(
                    conn, category="STANDARD_CHANGED", severity="HIGH",
                    title=f"[기준 개정] {self.name} {std['code']}",
                    body=(f"현행 기준 문서가 바뀌었습니다.\n{changed}\n"
                          f"이 소스는 값을 기계 판독할 수 없어 자동 대조가 안 됩니다 — "
                          f"원문을 열어 지침 배포값과 직접 대조하십시오.\n{std.get('url') or ''}"),
                    source=self.name)
        latest = max((x.get("effective") or "") for x in stds) or None
        return CollectResult(http_status=200, records_received=len(stds), records_valid=len(stds),
                             data_date=latest, warnings=changes[:5],
                             content_hash=sha("|".join(sorted(
                                 f"{x['code']}:{x.get('published')}:{x.get('effective')}:{x.get('revision')}"
                                 for x in stds))),
                             schema_hash=sha("code,published,effective,revision"))


class ChinaWatchCollector(StandardWatchCollector):
    """중국 GB 2763 — CFSA 식품안전국가표준 데이터검색플랫폼의 현행판 목록."""
    name = "China"

    def current_standards(self, s) -> list[dict]:
        try:
            r = s.post(CN_SEARCH_URL,
                       data={"isLength": "9999", "num_tn": "99", "standard_type": "",
                             "keyword": "农药最大残留限量"},
                       headers={"Referer": CN_SOURCE_PAGE}, timeout=60)
        except Exception as e:
            raise SourceUnavailable(f"CFSA 접속 실패: {e}")
        if r.status_code != 200:
            raise SourceUnavailable(f"CFSA HTTP {r.status_code}")
        try:
            rows = r.json()
        except ValueError:
            raise ParserError("CFSA 응답이 JSON 이 아님 — 플랫폼 구조 변경 의심")
        out = []
        for x in rows:
            code = (x.get("CODE") or "").strip()
            if not code.startswith("GB 2763"):
                continue                      # 공고문 등 판이 없는 항목 제외
            out.append({"code": code, "published": x.get("PDATE"),
                        "effective": x.get("SSRQ"), "revision": None,
                        "url": CN_SOURCE_PAGE})
        return out


class AustraliaWatchCollector(StandardWatchCollector):
    """호주 FSANZ Schedule 20 — 연방입법등록부의 현행 컴필레이션."""
    name = "Australia"

    def current_standards(self, s) -> list[dict]:
        try:
            r = s.get(AU_VERSIONS_URL,
                      params={"$filter": f"titleId eq '{AU_SCHEDULE20_TITLE}' and isCurrent eq true"},
                      timeout=60)
        except Exception as e:
            raise SourceUnavailable(f"FRL 접속 실패: {e}")
        if r.status_code != 200:
            raise SourceUnavailable(f"FRL HTTP {r.status_code}")
        rows = r.json().get("value", [])
        return [{"code": "Food Standards Code Schedule 20",
                 "published": (x.get("registeredAt") or "")[:10],
                 "effective": (x.get("start") or "")[:10],
                 "revision": f"compilation {x.get('compilationNumber')} ({x.get('registerId')})",
                 "url": f"https://www.legislation.gov.au/{x.get('registerId')}"} for x in rows]


class SingaporeWatchCollector(StandardWatchCollector):
    """싱가폴 Food Regulations 제30조(농약 잔류) + 제9부칙.

    제9부칙은 HTML 로 파싱되지만 등재 성분이 94종뿐이고 대상 12성분 중 1종(델타메트린)만
    들어 있다. 미등재 성분에 어떤 규칙이 적용되는지(금지인지, 다른 기준을 준용하는지)를
    규정에서 확인하지 못했으므로 **값 대조는 하지 않는다** — 모르는 규칙을 추정해 판정하면
    없는 위반을 만들거나 실제 위반을 놓친다(§30).

    대신 개정을 감시한다. SSO 는 조문 단위 판 정보를 준다:
      provTimelineIdx / provTimelineLen  → 30조가 몇 번째 판인지
      ValidDate=YYYYMMDD                 → 문서 시행일 이력
    30조가 개정되면 판 수가 늘어난다.
    """
    name = "Singapore"

    def current_standards(self, s) -> list[dict]:
        # SSO 는 기본 UA 를 403 으로 막는다(실측) — 브라우저 UA 필요.
        s.headers["User-Agent"] = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")
        try:
            r = s.get(SG_REG30_URL, timeout=60)
        except Exception as e:
            raise SourceUnavailable(f"SSO 접속 실패: {e}")
        if r.status_code != 200:
            raise SourceUnavailable(f"SSO HTTP {r.status_code}")
        idx = re.search(r'"provTimelineIdx":(\d+)', r.text)
        total = re.search(r'"provTimelineLen":(\d+)', r.text)
        dates = sorted(set(re.findall(r"ValidDate=(\d{8})", r.text)))
        if not (idx and total and dates):
            raise ParserError("SSO 판 정보 파싱 실패 — 페이지 구조 변경 의심")
        latest = dates[-1]
        return [{"code": "Food Regulations reg 30 · Ninth Schedule",
                 "published": None,
                 "effective": f"{latest[:4]}-{latest[4:6]}-{latest[6:]}",
                 "revision": f"reg30 {int(idx.group(1)) + 1}/{total.group(1)}판",
                 "url": SG_REG30_URL}]
