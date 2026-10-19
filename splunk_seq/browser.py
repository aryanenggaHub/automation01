"""Browser the user logs into; its cookies authenticate every search (spec §6, ADR 0001)."""

from __future__ import annotations

import os
import time
from typing import Callable

from .config import Config
from .paths import app_dir, resolve_in_app

PROFILE_DIR = "browser-profile"


def ca_cert_env(cfg: Config) -> dict[str, str]:
    """Environment that makes Playwright's HTTP client trust the company CA (read when the driver starts)."""
    if not cfg.browser.ca_cert_file:
        return {}
    return {"NODE_EXTRA_CA_CERTS": str(resolve_in_app(cfg.browser.ca_cert_file))}


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

        os.environ.update(ca_cert_env(self.cfg))
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
            pass  # e.g. slow SSO redirect; login is detected by polling, not by this load
        return self

    def __exit__(self, *exc) -> bool:
        self.context.close()
        self._playwright.stop()
        return False

    def _logged_in(self) -> bool:
        url = f"{self.cfg.splunk.url}/{self.cfg.splunk.locale}/splunkd/__raw/services/authentication/current-context?output_mode=json"
        response = self.context.request.get(url, max_redirects=0)
        return response.status == 200 and "json" in response.headers.get("content-type", "")

    def wait_for_login(self) -> bool:
        self.log(f"Log in to Splunk in the browser window (waiting up to {self.cfg.splunk.login_timeout_seconds}s)...")
        seen: set[str] = set()

        def report(exc: Exception) -> None:
            message = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            if message not in seen:
                seen.add(message)
                self.log(f"  Login check failed: {message}")

        return wait_until(self._logged_in, self.cfg.splunk.login_timeout_seconds, on_error=report, should_stop=self.should_stop)

    def post(self, url: str, form: dict[str, str], headers: dict[str, str], timeout_s: float) -> tuple[int, str, str]:
        response = self.context.request.post(
            url, form=form, headers=headers, timeout=timeout_s * 1000, max_redirects=0
        )
        return response.status, response.headers.get("content-type", ""), response.text()

    def cookies(self) -> list[dict]:
        return self.context.cookies()
