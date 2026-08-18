"""MRL 값 정규화 및 RDA 혼합제 파이프-성분 정렬 (§2·§13, STEP4 실증).

모든 비교는 이 모듈이 만든 구조화 값 위에서 deterministic하게 이뤄진다(§5).
"""
from __future__ import annotations

import re

from .models import Mrl, MrlKind

_NUM = re.compile(r"-?\d+(?:\.\d+)?")
_EXEMPT_WORDS = {"면제", "exempt", "exemption", "exempted"}


def parse_scalar(raw: str | None, *, default_marker: str = "*") -> Mrl:
    """단일 MRL 문자열을 정규화. RDA(한국/외국 세그먼트), Japan 값 등에 사용.

    처리: '-'=미설정, '면제'=Exemption, '0.05*'/'(*)'=기본값, 'delete'=삭제(미설정 취급).
    """
    if raw is None:
        return Mrl(MrlKind.NOT_SET, raw="")
    s = str(raw).strip()
    low = s.lower()
    if s in ("", "-", "—"):
        return Mrl(MrlKind.NOT_SET, raw=s)
    if low in {"delete", "deleted", "삭제"}:
        return Mrl(MrlKind.NOT_SET, raw=s, note="삭제됨")
    if low in _EXEMPT_WORDS:
        return Mrl(MrlKind.EXEMPT, raw=s)
    is_default = default_marker in s or "(*)" in s or low.endswith("lod")
    m = _NUM.search(s)
    if not m:
        return Mrl(MrlKind.UNKNOWN, raw=s)
    val = float(m.group())
    if is_default:
        return Mrl(MrlKind.LOQ_DEFAULT, value=val, raw=s, is_default=True)
    return Mrl(MrlKind.NORMAL, value=val, raw=s)


def parse_eu(mrl_value, mrl_lod, mrl_display) -> Mrl:
    """EU product-current-mrl-all-residues 레코드 → Mrl.

    MRL_LOD == '*' (또는 display가 '*'로 끝남) 이면 기본값/LOQ.
    """
    disp = (str(mrl_display) if mrl_display is not None else "") or ""
    lod = (str(mrl_lod) if mrl_lod is not None else "").strip()
    is_default = lod == "*" or disp.strip().endswith("*")
    try:
        val = float(mrl_value)
    except (TypeError, ValueError):
        return parse_scalar(disp or None)
    if is_default:
        return Mrl(MrlKind.LOQ_DEFAULT, value=val, raw=disp or f"{val:g}*", is_default=True)
    return Mrl(MrlKind.NORMAL, value=val, raw=disp or f"{val:g}")


def parse_codex(mrl_cell: str, symbol: str = "") -> Mrl:
    """Codex 'X mg/kg' + Symbol('(*)','Po') → Mrl."""
    s = (mrl_cell or "").strip()
    is_default = "(*)" in symbol or "(*)" in s
    m = _NUM.search(s)
    if not m:
        return parse_scalar(s or None)
    val = float(m.group())
    if is_default:
        return Mrl(MrlKind.LOQ_DEFAULT, value=val, raw=s, is_default=True)
    return Mrl(MrlKind.NORMAL, value=val, raw=s)


# ---- RDA 혼합제 파이프-성분 정렬 (STEP4 확정 규칙) ----

_FORMULATION = re.compile(r"\(([^)]*)\)\s*$")   # 끝의 (액상수화제) 등 제형


def split_rda_product(pumokmyeong: str) -> tuple[list[str], str]:
    """RDA 품목명 → (유효성분 리스트, 제형).

    예: '디페노코나졸.플루디옥소닐(수화제)' → (['디페노코나졸','플루디옥소닐'], '수화제')
    """
    name = (pumokmyeong or "").strip()
    form = ""
    mm = _FORMULATION.search(name)
    if mm:
        form = mm.group(1).strip()
        name = name[: mm.start()].strip()
    ingredients = [p.strip() for p in name.split(".") if p.strip()]
    return ingredients, form


def align_pipe(pumokmyeong: str, pipe_value: str) -> dict[str, Mrl]:
    """품목명 유효성분과 파이프('|') MRL 배열을 위치 대응시켜 {성분: Mrl} 반환.

    세그먼트 수가 성분 수와 다르면 가능한 위치까지만 매핑(길이 불일치는 note로 남김).
    """
    ingredients, _form = split_rda_product(pumokmyeong)
    segs = [s.strip() for s in (pipe_value or "").split("|")]
    out: dict[str, Mrl] = {}
    for i, ing in enumerate(ingredients):
        seg = segs[i] if i < len(segs) else None
        mrl = parse_scalar(seg)
        if len(segs) != len(ingredients):
            mrl.note = (mrl.note + " ; 성분/세그먼트 수 불일치").strip(" ;")
        out[ing] = mrl
    return out
