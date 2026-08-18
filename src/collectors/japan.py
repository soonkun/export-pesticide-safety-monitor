"""Japan (CAA/MHLW Positive List) collector — jpn-pesticides-database.

주의: 이 소스는 bulk/API가 없고 폼 크롤링이며, 서버가 봇/해외 IP를 403으로 차단하는 것이
관측되었다(STEP4). 또한 §30 원칙상 사이트 구조를 자동 추측해 파서를 임의 구성하지 않는다.

따라서 현재 구현은:
  - 검색 페이지 접근으로 소스 가용성만 확인한다.
  - 접근 차단 시 SOURCE_UNAVAILABLE → Fail-safe(§22)로 이어진다(RDA 캐시값을 최신처럼 쓰지 않음).
  - 접근은 되나 상세표 파서가 아직 국내망에서 검증되지 않았으면 PARSER_ERROR로 명확히 남긴다.
국내망에서 상세(showDetail) 응답을 확보해 검증한 뒤 파서를 추가하는 것이 다음 단계다.
"""
from __future__ import annotations

from ..config import JAPAN_BASE
from ..http import ParserError, SourceUnavailable
from .base import BaseCollector, CollectResult, sha


class JapanCollector(BaseCollector):
    name = "Japan"

    def collect(self, conn, s) -> CollectResult:
        headers = {
            "Accept-Language": "en,ja;q=0.8",
            "Referer": JAPAN_BASE,
        }
        try:
            r = s.get(JAPAN_BASE + "index_en.pl", headers=headers, timeout=40)
        except Exception as e:
            raise SourceUnavailable(f"Japan 접속 실패: {e}")
        if r.status_code == 403 or (r.status_code == 200 and len(r.text) < 500):
            raise SourceUnavailable(
                f"Japan 검색시스템 접근 차단(HTTP {r.status_code}, len={len(r.text)}). "
                "봇 차단/해외 IP 제한 가능 — 국내망에서 재시도 필요.")
        if r.status_code != 200:
            raise SourceUnavailable(f"Japan HTTP {r.status_code}")
        # 접근은 됨: 상세 파서는 국내망 검증 전까지 자동 구성 금지(§30)
        raise ParserError(
            "Japan 검색 페이지 접근 성공. 상세(showDetail) 응답 파서는 국내망 검증 후 추가 예정 "
            "(§30 자동 추측 금지). 현재는 RDA 캐시값을 최신성 LOW로 표기하는 Fail-safe로 처리.")
