"""Codex (FAO/WHO) collector - internal JSON endpoint.

detail 페이지가 아니라 DataTables가 쓰는 JSON을 직접 호출한다(STEP4에서 발견):
  /jsoncodexpest/jsonrequest/pesticides/details.html?id={p_id}&lang=en
mrls.mrl[] 의 commodity.name <-> master codex_name(그룹 포함) 매칭.
"""
from __future__ import annotations

import json
import re

from .. import db
from ..http import ParserError
from ..masters import COMMODITIES, PESTICIDES
from ..normalize import parse_codex
from .base import BaseCollector, CollectResult, sha

CODEX_JSON = "https://www.fao.org/jsoncodexpest/jsonrequest/pesticides/details.html"
# JSON 응답에 raw 제어문자(0x00-0x1f)가 섞여 있어 제거(사이트 JS와 동일 처리).
_CTRL = re.compile("[" + "".join(chr(c) for c in range(0x20)) + "]+")


class CodexCollector(BaseCollector):
    name = "Codex"

    def collect(self, conn, s) -> CollectResult:
        total = stored = 0
        for pest_ko, pm in PESTICIDES.items():
            pid = pm.get("codex_pid")
            if not pid:
                continue
            data = self._fetch(s, pid)
            mrls = (data.get("mrls") or {}).get("mrl") or []
            total += len(mrls)
            table = {}
            for m in mrls:
                cname = ((m.get("commodity") or {}).get("name") or "").strip().lower()
                if cname:
                    table[cname] = (m.get("mrlFormatted") or m.get("mrl") or "",
                                    m.get("lod") or "", m.get("cacYear") or "")
            for commodity_ko, cm in COMMODITIES.items():
                key = (cm.get("codex_name") or "").strip().lower()
                if key in table:
                    raw, lod, year = table[key]
                    mrl = parse_codex(raw, lod)
                    db.record_foreign_mrl(conn, source=self.name, pesticide_en=pm["english"],
                                          commodity_ko=commodity_ko,
                                          commodity_src=cm.get("codex_name"), mrl=mrl,
                                          effective_date=year)
                    stored += 1
        return CollectResult(http_status=200, records_received=total, records_valid=stored,
                             content_hash=sha(str(total)), schema_hash=sha("codex.mrls.mrl.commodity"))

    def _fetch(self, s, pid: int) -> dict:
        r = s.get(CODEX_JSON, params={"id": pid, "lang": "en"}, timeout=40)
        r.raise_for_status()
        txt = _CTRL.sub("", r.text)
        try:
            return json.loads(txt)
        except json.JSONDecodeError as e:
            raise ParserError(f"Codex JSON parse fail (p_id={pid}): {e}")
