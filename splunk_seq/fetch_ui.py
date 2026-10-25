"""Run searches in Splunk's Search page and read the results table (ADR 0003).

Everything goes through the browser, so Chrome's own certificate store, proxy and login apply.
"""

from __future__ import annotations

import time
from typing import Callable
from urllib.parse import quote

from .browser import wait_until
from .config import Config
from .errors import LoginExpired, SearchError
from .models import Row
from .queries import ensure_table
from .ui_steps import Step, UiSteps

# Cell texts of every row, in one round trip: (rows, cell selector) -> [[text, ...], ...]
ROWS_JS = "(rows, cell) => rows.map(r => Array.from(r.querySelectorAll(cell), c => c.innerText.trim()))"
PAGE_LOAD_S = 30.0  # how long a Next click may take to show the next page


def _first_line(exc: Exception) -> str:
    return str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__


def _cell(text: str) -> str:
    return ", ".join(part.strip() for part in text.splitlines() if part.strip())  # multivalue cells


class UiFetcher:
    def __init__(
        self,
        cfg: Config,
        steps: UiSteps,
        page,
        log: Callable[[str], None] = print,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.cfg = cfg
        self.steps = steps
        self.page = page
        self.log = log
        self._sleep = sleep
        self._clock = clock

    # ---- helpers ------------------------------------------------------
    def _wait(self, check: Callable[[], bool], timeout_s: float) -> bool:
        return wait_until(check, timeout_s, 0.5, self._sleep, self._clock)

    def _visible(self, selector: str) -> bool:
        if not selector:
            return False
        try:
            return self.page.locator(selector).first.is_visible()
        except Exception:
            return False

    def _fail(self, message: str):
        if self._visible(self.steps.login_page):
            raise LoginExpired(message)
        raise SearchError(message)

    def _fill_in(self, text: str, values: dict[str, str], encode: bool) -> str:
        for key, value in values.items():
            # {url} and {locale} build the address itself; everything else is a URL parameter value.
            if encode and key not in ("url", "locale"):
                value = quote(value, safe="")
            text = text.replace("{" + key + "}", value)
        return text

    def _do(self, step: Step, values: dict[str, str]) -> None:
        timeout_ms = self.cfg.search.timeout_seconds * 1000
        if step.action == "goto":
            self.page.goto(self._fill_in(step.value, values, encode=True))
        elif step.action == "click":
            self.page.click(step.selector)
        elif step.action == "fill":
            self.page.fill(step.selector, self._fill_in(step.value, values, encode=False))
        elif step.action == "press":
            self.page.press(step.selector, step.value)
        else:
            self.page.wait_for_selector(step.selector, state="visible", timeout=timeout_ms)

    # ---- one search ---------------------------------------------------
    def run_search(self, query: str, earliest: str, latest: str) -> list[Row]:
        values = {
            "url": self.cfg.splunk.url,
            "locale": self.cfg.splunk.locale,
            "query": ensure_table(query),
            "earliest": earliest,
            "latest": latest,
        }
        for i, step in enumerate(self.steps.search, start=1):
            try:
                self._do(step, values)
            except Exception as exc:
                self._fail(f"UI step {i} ({step.action} {step.selector or step.value}) failed: {_first_line(exc)}")
        return self._results()

    def _results(self) -> list[Row]:
        r = self.steps.results
        watched = (self.steps.login_page, r.error, r.no_results, r.done)
        timeout = self.cfg.search.timeout_seconds
        if not self._wait(lambda: any(self._visible(s) for s in watched), timeout):
            self._fail(f"Search did not finish within {timeout}s (nothing matched results.done: {r.done})")
        if self._visible(self.steps.login_page):
            raise LoginExpired("Splunk login page shown")
        if self._visible(r.error):
            raise SearchError(" ".join(self.page.locator(r.error).first.inner_text().split()) or "Splunk reported an error")
        if self._visible(r.no_results):
            return []
        if not self._wait(lambda: self._visible(r.table) or self._visible(r.no_results), 10):
            raise SearchError(f"Search finished but no results table matched results.table: {r.table}")
        return [] if self._visible(r.no_results) else self._scrape()

    def _page_rows(self) -> list[list[str]]:
        r = self.steps.results
        return self.page.locator(r.table).first.locator(r.row).evaluate_all(ROWS_JS, r.cell)

    def _scrape(self) -> list[Row]:
        r = self.steps.results
        limit = self.cfg.search.max_rows
        headers = [h.strip() for h in self.page.locator(r.table).first.locator(r.header).all_inner_texts()]
        rows: list[Row] = []
        while True:
            page_rows = self._page_rows()
            for cells in page_rows:
                rows.append({h: _cell(c) for h, c in zip(headers, cells) if h})
                if len(rows) >= limit:
                    self.log(f"  Warning: stopped reading at search.max_rows = {limit} rows; later rows are missing")
                    return rows
            if not page_rows or not self._next_page(page_rows[0]):
                return rows

    def _next_page(self, first_row: list[str]) -> bool:
        r = self.steps.results
        if not r.next or not self._visible(r.next) or self._visible(r.next_disabled):
            return False
        button = self.page.locator(r.next).first
        if button.is_disabled():
            return False
        button.click()

        def moved() -> bool:
            rows = self._page_rows()
            return bool(rows) and rows[0] != first_row

        if not self._wait(moved, PAGE_LOAD_S):
            raise SearchError(f"Next page did not load within {PAGE_LOAD_S:.0f}s (results.next: {r.next})")
        return True

    # ---- diagnostics for "Test UI steps" --------------------------------
    def selector_report(self) -> list[str]:
        r = self.steps.results
        named = [("login_page", self.steps.login_page)] + [
            (f"results.{name}", getattr(r, name))
            for name in ("done", "error", "no_results", "table", "next", "next_disabled")
        ]
        lines = []
        for name, selector in named:
            if not selector:
                continue
            try:
                count = self.page.locator(selector).count()
                state = f"{count} match(es), {'visible' if self._visible(selector) else 'not visible'}"
            except Exception as exc:
                state = f"invalid selector ({_first_line(exc)})"
            lines.append(f"  {name}: {state}  [{selector}]")
        return lines
