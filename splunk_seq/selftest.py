"""`--selftest`: prove the packaged app can find Playwright's bundled driver (standalone spec §3)."""

from __future__ import annotations

from pathlib import Path


def run_selftest(out_dir: Path) -> bool:
    try:
        from playwright.sync_api import sync_playwright

        # Starting the driver proves the bundled Node runtime and Playwright package are present and run.
        sync_playwright().start().stop()
        (Path(out_dir) / "selftest.ok").write_text("ok\n", encoding="utf-8")
        return True
    except Exception:
        return False
