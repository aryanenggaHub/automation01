"""`--selftest`: prove the packaged app can find Playwright's bundled driver (standalone spec §3)."""

from __future__ import annotations

from pathlib import Path


def run_selftest(out_dir: Path) -> bool:
    try:
        import playwright.sync_api  # noqa: F401
        from playwright._impl._driver import compute_driver_executable

        driver = compute_driver_executable()
        paths = driver if isinstance(driver, tuple) else (driver,)
        if not all(Path(p).exists() for p in paths):
            return False
        # Start and stop the driver: proves the bundled Node runtime actually runs.
        playwright.sync_api.sync_playwright().start().stop()
        (Path(out_dir) / "selftest.ok").write_text("ok\n", encoding="utf-8")
        return True
    except Exception:
        return False
