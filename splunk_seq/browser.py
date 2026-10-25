"""The browser the user logs into; every search then runs in its Search page (spec §6, ADR 0003)."""

from __future__ import annotations

import time
from typing import Callable

from .config import Config
from .paths import app_dir

PROFILE_DIR = "browser-profile"


def wait_until(
    check: Callable[[], bool],
    timeout_s: float,
    interval_s: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    on_error: Callable[[Exception], None] | None = None,
    should_stop: Callable[[], bool] = lambda: False,
) -> bool:
    """Poll check until it returns True (-> True), or timeout_s passes or should_stop() (-> False).

    An exception from check counts as not ready and is passed to on_error.
    """
    deadline = clock() + timeout_s
    while True:
        if should_stop():
            return False
        try:
            if check():
                return True
        except Exception as exc:
            if on_error is not None:
                on_error(exc)
        if clock() >= deadline:
            return False
        sleep(interval_s)


class BrowserSession:
    def __init__(self, cfg: Config, should_stop: Callable[[], bool] = lambda: False, log: Callable[[str], None] = print):
        self.cfg = cfg
        self.log = log
        self.should_stop = should_stop
        self._playwright = None
        self.context = None
        self.page = None

    def __enter__(self) -> "BrowserSession":
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        try:
            # Persistent profile: the Splunk login (and any sign-in extension) survives between runs.
            self.context = self._playwright.chromium.launch_persistent_context(
                str(app_dir() / PROFILE_DIR),
                channel=self.cfg.browser.channel,
                headless=False,
                ignore_https_errors=self.cfg.browser.ignore_https_errors,
            )
        except Exception:
            self._playwright.stop()
            raise
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        try:
            self.page.goto(self.cfg.splunk.url)
        except Exception:
            pass  # e.g. slow SSO redirect; the user confirms the login, not this load
        return self

    def __exit__(self, *exc) -> bool:
        self.context.close()
        self._playwright.stop()
        return False
