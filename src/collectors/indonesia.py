"""Indonesia (SNI 7313) collector — 담당자 수동 입력 파일 기반.

인도네시아 현행 MRL 은 국가표준 SNI 7313:2024(272 성분 × 406 품목) 이다.
**자동 수집이 불가능하다** — 실측(2026-08-20):
  · `bsn.go.id`(표준 원문 게시처)  : 해외에서 연결 타임아웃 (이 서버·외부 fetch 모두)
  · `brmp.pertanian.go.id`         : Cloudflare 403
  · `repository.pertanian.go.id`   : 403
  · data.go.id 는 열리지만 잔류농약 기준 데이터셋을 제공하지 않음
다른 인니 정부 사이트(kemendag.go.id)는 열리므로 국가 단위 차단은 아니고, 해당 호스트들이
해외 트래픽을 막는 것으로 보인다.

그래서 이 소스만 **수동 입력**으로 둔다. SNI 7313 은 2008 → 2024 로 16년 만에 개정된
저빈도 표준이라 매일 긁을 이유가 없고, 담당자가 표준을 확보해 CSV 로 한 번 넣으면 된다.

파일: data/manual/indonesia_mrl.csv (UTF-8, 헤더 필수)
    pesticide_en,commodity_ko,mrl_ppm,standard,effective_date
    Azoxystrobin,사과,2,SNI 7313:2024,2024-12-01
commodity_ko 는 지침의 작목명을 그대로 쓴다 — 중간 매핑을 만들지 않는다(오역 지점 제거).
파일이 없으면 SOURCE_UNAVAILABLE 로 두어 "미확인"임이 화면에 그대로 남는다(§22).
"""
from __future__ import annotations

import csv

from .. import db
from ..config import INDONESIA_FILE, INDONESIA_STANDARD_URL
from ..http import ParserError, SourceUnavailable
from ..masters import PESTICIDES
from ..normalize import parse_scalar
from .base import BaseCollector, CollectResult, sha

REQUIRED_COLUMNS = {"pesticide_en", "commodity_ko", "mrl_ppm"}


def read_rows() -> list[dict]:
    """수동 입력 파일을 읽는다. 없으면 빈 목록(에러 아님 — 호출부에서 판단)."""
    if not INDONESIA_FILE.exists():
        return []
    with INDONESIA_FILE.open(encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f) if (r.get("pesticide_en") or "").strip()]


def known_commodities() -> set[str]:
    """수동 파일에 실제로 들어 있는 작목 — coverage 계산에 쓴다."""
    return {(r.get("commodity_ko") or "").strip() for r in read_rows()} - {""}


class IndonesiaCollector(BaseCollector):
    name = "Indonesia"

    def collect(self, conn, s) -> CollectResult:
        rows = read_rows()
        if not rows:
            raise SourceUnavailable(
                f"SNI 7313 수동 입력 파일 없음 ({INDONESIA_FILE}). "
                f"인니 표준 사이트가 해외 접근을 차단해 자동 수집 불가 — {INDONESIA_STANDARD_URL} "
                "에서 표준을 받아 CSV(pesticide_en,commodity_ko,mrl_ppm,standard,effective_date)로 넣으십시오.")
        missing = REQUIRED_COLUMNS - set(rows[0].keys())
        if missing:
            raise ParserError(f"수동 입력 파일 컬럼 누락: {sorted(missing)}")

        by_en = {pm["english"].lower(): pm["english"] for pm in PESTICIDES.values()}
        stored = 0
        warnings: list[str] = []
        dates: list[str] = []
        for r in rows:
            en = by_en.get((r["pesticide_en"] or "").strip().lower())
            commodity = (r["commodity_ko"] or "").strip()
            if not en:
                warnings.append(f"마스터에 없는 성분: {r['pesticide_en']}")
                continue
            if not commodity:
                continue
            standard = (r.get("standard") or "SNI 7313").strip()
            eff = (r.get("effective_date") or "").strip()
            if eff:
                dates.append(eff)
            db.record_foreign_mrl(
                conn, source=self.name, pesticide_en=en, commodity_ko=commodity,
                commodity_src=commodity, mrl=parse_scalar(r["mrl_ppm"]),
                effective_date=eff or None, source_url=INDONESIA_STANDARD_URL,
                basis=f"{standard} (담당자 수동 입력)")
            stored += 1

        if not stored:
            raise ParserError("수동 입력 파일에서 유효한 행을 하나도 읽지 못함")
        return CollectResult(http_status=None, records_received=stored, records_valid=stored,
                             data_date=(max(dates) if dates else None),
                             warnings=sorted(set(warnings))[:5],
                             content_hash=sha(f"{stored}:{max(dates) if dates else ''}"),
                             schema_hash=sha(",".join(sorted(REQUIRED_COLUMNS))))
