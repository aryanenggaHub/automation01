"""Re-login handling around a search function (spec §6)."""

from __future__ import annotations

from typing import Callable

from .errors import LoginExpired, SearchError
from .models import Row, SearchFn

RELOGIN_MESSAGE = "Splunk login expired — log in again in the browser window"


def with_relogin(search: SearchFn, relogin: Callable[[], bool], log: Callable[[str], None]) -> SearchFn:
    def run_search(query: str, earliest: str, latest: str) -> list[Row]:
        try:
            return search(query, earliest, latest)
        except LoginExpired:
            log(RELOGIN_MESSAGE)
            if not relogin():
                raise SearchError("Login expired and re-login timed out") from None
        try:
            return search(query, earliest, latest)
        except LoginExpired as exc:
            raise SearchError(f"Login expired again after re-login ({exc})") from None

    return run_search
