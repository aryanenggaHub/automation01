"""Fetch strategy: re-login handling, auto proxy→UI fallback, and the UI fetcher (spec §6–§7)."""

from __future__ import annotations

from typing import Callable

from .errors import LoginExpired, ProxyUnavailable, SearchError
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


class AutoFetcher:
    """Use the proxy; if the run's first proxy search finds it blocked, use the UI from then on."""

    def __init__(self, proxy: SearchFn, ui: SearchFn, log: Callable[[str], None]):
        self.proxy = proxy
        self.ui = ui
        self.log = log
        self._active: SearchFn | None = None

    def run_search(self, query: str, earliest: str, latest: str) -> list[Row]:
        if self._active is not None:
            return self._active(query, earliest, latest)
        try:
            rows = self.proxy(query, earliest, latest)
        except ProxyUnavailable as exc:
            self.log(f"Warning: splunkd web proxy unavailable ({exc}); switching to UI mode for this run")
            self._active = self.ui
            return self.ui(query, earliest, latest)
        self._active = self.proxy
        return rows


class UiFetcher:
    """Read results from the Splunk Search page. Built inside the target network (plan Task 8)."""

    def __init__(self, page):
        self.page = page

    def run_search(self, query: str, earliest: str, latest: str) -> list[Row]:
        raise SearchError("UI fallback not implemented yet")
