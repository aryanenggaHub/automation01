"""Browser the user logs into; its cookies authenticate every search (spec §6, ADR 0001)."""

from __future__ import annotations

import time
from typing import Callable

from .config import Config


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
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._playwright = None
        self._browser = None
        self.context = None
        self.page = None

    def __enter__(self) -> "BrowserSession":
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(channel=self.cfg.browser.channel, headless=False)
        self.context = self._browser.new_context(ignore_https_errors=self.cfg.browser.ignore_https_errors)
        self.page = self.context.new_page()
        self.page.goto(self.cfg.splunk.url)
        return self

    def __exit__(self, *exc) -> bool:
        self._browser.close()
        self._playwright.stop()
        return False

    def _logged_in(self) -> bool:
        url = f"{self.cfg.splunk.url}/{self.cfg.splunk.locale}/splunkd/__raw/services/authentication/current-context?output_mode=json"
        response = self.context.request.get(url, max_redirects=0)
        return response.status == 200 and "json" in response.headers.get("content-type", "")

    def wait_for_login(self) -> bool:
        print(f"Log in to Splunk in the browser window (waiting up to {self.cfg.splunk.login_timeout_seconds}s)...")
        seen: set[str] = set()

        def report(exc: Exception) -> None:
            message = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            if message not in seen:
                seen.add(message)
                print(f"  Login check failed: {message}")

        return wait_until(self._logged_in, self.cfg.splunk.login_timeout_seconds, on_error=report)

    def post(self, url: str, form: dict[str, str], headers: dict[str, str], timeout_s: float) -> tuple[int, str, str]:
        response = self.context.request.post(
            url, form=form, headers=headers, timeout=timeout_s * 1000, max_redirects=0
        )
        return response.status, response.headers.get("content-type", ""), response.text()

    def cookies(self) -> list[dict]:
        return self.context.cookies()
