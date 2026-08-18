"""상태 열거형 및 데이터 모델 (명세 §4·§12·§17·§21·§23)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RegStatus(str, Enum):
    """규정 비교 상태 (§4)."""
    MATCH = "MATCH"
    RDA_STRICTER = "RDA_STRICTER"
    RDA_HIGHER = "RDA_HIGHER"
    FOREIGN_CHANGED = "FOREIGN_CHANGED"
    UPCOMING_CHANGE = "UPCOMING_CHANGE"
    REGISTRATION_CHANGED = "REGISTRATION_CHANGED"
    USAGE_CHANGED = "USAGE_CHANGED"
    TARGET_CHANGED = "TARGET_CHANGED"
    NO_FOREIGN_STANDARD = "NO_FOREIGN_STANDARD"
    UNMAPPED = "UNMAPPED"
    AMBIGUOUS = "AMBIGUOUS"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    AI_ANALYZED = "AI_ANALYZED"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"

    @property
    def rank(self) -> int:
        return {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0}[self.value]


class Health(str, Enum):
    """System Health (§17)."""
    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    STALE = "STALE"
    FAILED = "FAILED"
    PARSER_ERROR = "PARSER_ERROR"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    SCHEMA_CHANGED = "SCHEMA_CHANGED"
    AUTH_ERROR = "AUTH_ERROR"
    UNKNOWN = "UNKNOWN"


class Freshness(str, Enum):
    FRESH = "FRESH"
    AGING = "AGING"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class Mapping(str, Enum):
    """매핑 상태 (§12)."""
    EXACT = "EXACT"
    IDENTIFIER_MATCH = "IDENTIFIER_MATCH"
    ALIAS_MATCH = "ALIAS_MATCH"
    MANUAL_MAPPING = "MANUAL_MAPPING"
    AI_SUGGESTED = "AI_SUGGESTED"
    AMBIGUOUS = "AMBIGUOUS"
    UNMAPPED = "UNMAPPED"


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class MrlKind(str, Enum):
    NORMAL = "NORMAL"          # 정상 수치
    EXEMPT = "EXEMPT"          # 면제 / Exemption
    LOQ_DEFAULT = "LOQ_DEFAULT"  # 기본값/정량한계(예: EU 0.05*, Codex (*))
    NOT_SET = "NOT_SET"        # 미설정 ('-')
    UNKNOWN = "UNKNOWN"


@dataclass
class Mrl:
    """정규화된 MRL 값 하나."""
    kind: MrlKind
    value: float | None = None      # mg/kg(=ppm)
    raw: str = ""
    note: str = ""
    is_default: bool = False        # LOQ/기본값 여부

    def display(self) -> str:
        if self.kind == MrlKind.EXEMPT:
            return "면제"
        if self.kind == MrlKind.NOT_SET:
            return "-"
        if self.value is None:
            return self.raw or "?"
        s = f"{self.value:g}"
        return s + ("*" if self.is_default else "")
