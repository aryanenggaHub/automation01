"""One run from login to workbook, shared by the CLI and the window (standalone spec §7)."""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from .browser import BrowserSession
from .config import Config, ConfigError
from .errors import SearchError
from .fetch import with_relogin
from .fetch_ui import UiFetcher
from .paths import app_dir
from .queries import render_session_query
from .runner import run
from .ui_steps import UI_STEPS_NAME, load_ui_steps
from .workbook import SequenceWorkbook, output_path

# Blocks until the user says they are logged in (-> True), or the timeout / Stop (-> False).
ConfirmFn = Callable[[float], bool]


@dataclass
class JobResult:
    exit_code: int
    workbook_path: Path | None
    log_path: Path | None
    tally: dict[str, int] = field(default_factory=dict)


def execute(
    cfg: Config,
    apis: list[str],
    log: Callable[[str], None],
    confirm_login: ConfirmFn,
    should_stop: Callable[[], bool] = lambda: False,
    session_factory=BrowserSession,
    now: Callable[[], datetime] = datetime.now,
    probe: bool = False,
) -> JobResult:
    """Run every API, or with probe=True only test ui_steps.yaml on the first API's Session Query."""
    path = output_path(cfg.output, now(), app_dir())
    log_path = path.with_suffix(".log")
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = log_path.open("w", encoding="utf-8")
    except OSError as exc:
        log(f"Cannot write to output folder {log_path.parent}: {exc}")
        return JobResult(1, None, None)

    # The log file is open before the browser starts, so login and start-up failures are in it too.
    with log_file:

        def tee(line: str) -> None:
            log(line)
            log_file.write(line + "\n")
            log_file.flush()

        for warning in cfg.warnings:
            tee(warning)
        try:
            steps = load_ui_steps(app_dir() / UI_STEPS_NAME)
        except ConfigError as exc:
            tee(str(exc))
            return JobResult(1, None, log_path)
        try:
            session = session_factory(cfg, should_stop, tee).__enter__()
        except Exception as exc:
            tee(f"Could not start the browser: {exc}")
            return JobResult(1, None, log_path)
        try:
            timeout = cfg.splunk.login_timeout_seconds
            tee(f"Log in to Splunk in the browser window, then confirm (waiting up to {timeout}s)...")
            if not confirm_login(timeout):
                tee("Stopped" if should_stop() else "Login was not confirmed in time")
                return JobResult(2, None, log_path)
            fetcher = UiFetcher(cfg, steps, session.page, tee)
            if probe:
                return _probe(cfg, apis[0], fetcher, tee, path, log_path)
            search = with_relogin(fetcher.run_search, lambda: confirm_login(timeout), tee)
            tally = run(apis, cfg, search, SequenceWorkbook(path, len(apis)), log=tee, should_stop=should_stop)
            tee(" ".join(f"{status}={count}" for status, count in tally.items()))
            if not path.exists():
                tee("No workbook written (stopped before the first Input API finished)")
                return JobResult(0, None, log_path, tally)
            tee(f"Wrote {path}")
            return JobResult(0, path, log_path, tally)
        except Exception:
            tee("Unexpected error:\n" + traceback.format_exc())
            return JobResult(1, None, log_path)
        finally:
            session.__exit__(None, None, None)


def _probe(cfg: Config, api: str, fetcher: UiFetcher, tee, path: Path, log_path: Path) -> JobResult:
    """Run one Session Query and report what each ui_steps.yaml selector matched, plus a screenshot."""
    tee(f"Testing UI steps with the Session Query for {api}")
    try:
        rows = fetcher.run_search(render_session_query(cfg.session, api), cfg.search.earliest, cfg.search.latest)
        tee(f"UI steps OK: {len(rows)} row(s); columns: {', '.join(rows[0]) if rows else '(no rows)'}")
        code = 0
    except SearchError as exc:
        tee(f"UI steps failed: {exc}")
        code = 1
    tee("Selectors on the page now:")
    for line in fetcher.selector_report():
        tee(line)
    shot = path.with_name(path.stem + "_probe.png")
    try:
        fetcher.page.screenshot(path=str(shot), full_page=True)
        tee(f"Screenshot: {shot}")
    except Exception as exc:
        tee(f"Could not save a screenshot: {exc}")
    html = log_path.with_name("ui_test_page.html")  # one file, overwritten by every test
    try:
        html.write_text(fetcher.page.content(), encoding="utf-8")
        tee(f"Page HTML (contains search results): {html}")
    except Exception as exc:
        tee(f"Could not save page HTML: {exc}")
    return JobResult(code, None, log_path)
