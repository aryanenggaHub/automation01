"""Shared types for one run: rows, search function shape, per-API results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

Row = dict[str, str]
SearchFn = Callable[[str, str, str], list[Row]]  # (query, earliest, latest) -> rows

OK = "OK"
NO_SESSION = "NO_SESSION"
ERROR = "ERROR"

UNKNOWN_LAYER = "UNKNOWN_LAYER"
BAD_TIMESTAMP = "BAD_TIMESTAMP"
AMBIGUOUS = "AMBIGUOUS"


@dataclass
class SessionResult:
    session_id: str
    rows: list[Row]
    flags: list[str]


@dataclass
class ApiResult:
    input_api: str
    status: str
    sessions: list[SessionResult] = field(default_factory=list)
    error: str = ""
