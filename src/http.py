"""공용 HTTP 세션 및 예외."""
from __future__ import annotations

import requests

from .config import HTTP_TIMEOUT, HTTP_VERIFY, USER_AGENT


class SourceUnavailable(Exception): ...
class AuthError(Exception): ...
class ParserError(Exception): ...
class SchemaChanged(Exception): ...


def session() -> requests.Session:
    s = requests.Session()
    s.verify = HTTP_VERIFY
    s.headers["User-Agent"] = USER_AGENT
    if not HTTP_VERIFY:
        import urllib3
        urllib3.disable_warnings()
    return s


def get_json(s: requests.Session, url: str, **kw):
    kw.setdefault("timeout", HTTP_TIMEOUT)
    r = s.get(url, **kw)
    return r


def get(s: requests.Session, url: str, **kw):
    kw.setdefault("timeout", HTTP_TIMEOUT)
    return s.get(url, **kw)
