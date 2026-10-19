"""One run from login to workbook, shared by the CLI and the window (standalone spec §7)."""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from .browser import BrowserSession
from .config import Config
from .fetch import with_relogin
from .fetch_proxy import ProxyFetcher
from .paths import app_dir
from .runner import run
from .workbook import SequenceWorkbook, output_path


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
    should_stop: Callable[[], bool] = lambda: False,
    session_factory=BrowserSession,
    now: Callable[[], datetime] = datetime.now,
) -> JobResult:
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

        try:
            session = session_factory(cfg, should_stop, tee).__enter__()
        except Exception as exc:
            tee(f"Could not start the browser: {exc}")
            return JobResult(1, None, log_path)
        try:
            if not session.wait_for_login():
                tee("Stopped" if should_stop() else "Login was not detected in time")
                return JobResult(2, None, log_path)
            search = with_relogin(ProxyFetcher(cfg, session.post, session.cookies).run_search, session.wait_for_login, tee)
            tally = run(apis, cfg, search, SequenceWorkbook(path, len(apis)), log=tee, should_stop=should_stop)
            tee(f"Wrote {path}")
            tee(" ".join(f"{status}={count}" for status, count in tally.items()))
            return JobResult(0, path, log_path, tally)
        except Exception:
            tee("Unexpected error:\n" + traceback.format_exc())
            return JobResult(1, None, log_path)
        finally:
            session.__exit__(None, None, None)
