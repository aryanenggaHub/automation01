from datetime import datetime

import pytest
from conftest import FakeBrowser

import splunk_seq.job as job
from splunk_seq.config import parse_config
from splunk_seq.job import execute

NOW = datetime(2026, 10, 19, 9, 30, 0)


@pytest.fixture
def cfg(tmp_path):
    return parse_config({
        "splunk": {"url": "https://s:8000"},
        "session": {"query": "x"},
        "sequence": {"query": "y"},
        "output": {"dir": str(tmp_path / "out")},
    })


@pytest.fixture
def browser(monkeypatch):
    monkeypatch.setattr(FakeBrowser, "start_error", None)
    return FakeBrowser


def confirmed(timeout_s):
    return True


def not_confirmed(timeout_s):
    return False


def fake_run(apis, cfg, search, workbook, log=print, should_stop=lambda: False):
    log("hello")
    workbook.save()
    return {"OK": len(apis), "NO_SESSION": 0, "ERROR": 0}


def test_execute_tees_log_to_file(cfg, browser, monkeypatch):
    monkeypatch.setattr(job, "run", fake_run)
    lines = []
    result = execute(cfg, ["/a"], lines.append, confirmed, session_factory=browser, now=lambda: NOW)
    assert result.exit_code == 0 and result.tally["OK"] == 1
    assert "hello" in lines
    assert result.log_path == result.workbook_path.with_suffix(".log")
    assert "hello" in result.log_path.read_text(encoding="utf-8")
    assert result.workbook_path.name == "api_sequence_20261019_093000.xlsx"


def test_execute_login_timeout_exit_2(cfg, browser, monkeypatch):
    lines = []
    result = execute(cfg, ["/a"], lines.append, not_confirmed, session_factory=browser, now=lambda: NOW)
    assert result.exit_code == 2 and result.workbook_path is None
    assert any("Login was not confirmed in time" in line for line in lines)


def test_execute_browser_start_failure_exit_1(cfg, browser, monkeypatch):
    monkeypatch.setattr(browser, "start_error", RuntimeError("profile in use"))
    lines = []
    result = execute(cfg, ["/a"], lines.append, confirmed, session_factory=browser, now=lambda: NOW)
    assert result.exit_code == 1
    assert any("Could not start the browser: profile in use" in line for line in lines)


def test_execute_stop_during_login_writes_nothing(cfg, browser, monkeypatch, tmp_path):
    lines = []
    result = execute(cfg, ["/a"], lines.append, not_confirmed, should_stop=lambda: True, session_factory=browser, now=lambda: NOW)
    assert any("Stopped" in line for line in lines)
    assert result.workbook_path is None
    assert not list((tmp_path / "out").glob("*.xlsx"))


def test_login_timeout_still_leaves_a_log_file(cfg, browser, monkeypatch):
    result = execute(cfg, ["/a"], lambda line: None, not_confirmed, session_factory=browser, now=lambda: NOW)
    assert "Login was not confirmed in time" in result.log_path.read_text(encoding="utf-8")


def test_browser_start_failure_is_in_log_file(cfg, browser, monkeypatch):
    monkeypatch.setattr(browser, "start_error", RuntimeError("profile in use"))
    result = execute(cfg, ["/a"], lambda line: None, confirmed, session_factory=browser, now=lambda: NOW)
    assert "Could not start the browser: profile in use" in result.log_path.read_text(encoding="utf-8")


def test_unexpected_error_logged_with_traceback(cfg, browser, monkeypatch):
    def boom(*args, **kwargs):
        raise ValueError("kaboom")

    monkeypatch.setattr(job, "run", boom)
    result = execute(cfg, ["/a"], lambda line: None, confirmed, session_factory=browser, now=lambda: NOW)
    text = result.log_path.read_text(encoding="utf-8")
    assert result.exit_code == 1
    assert "Traceback" in text and "kaboom" in text


def test_unwritable_output_folder_exit_1(cfg, browser, monkeypatch, tmp_path):
    (tmp_path / "out").write_text("a file where the folder should be", encoding="utf-8")
    lines = []
    result = execute(cfg, ["/a"], lines.append, confirmed, session_factory=browser, now=lambda: NOW)
    assert result.exit_code == 1
    assert any("Cannot write to output folder" in line for line in lines)


def test_stop_before_first_api_reports_no_workbook(cfg, browser, monkeypatch):
    def stopped_run(apis, cfg, search, workbook, log=print, should_stop=lambda: False):
        log("Stopped by user after 0 of 1 APIs")
        return {"OK": 0, "NO_SESSION": 0, "ERROR": 0}

    monkeypatch.setattr(job, "run", stopped_run)
    lines = []
    result = execute(cfg, ["/a"], lines.append, confirmed, session_factory=browser, now=lambda: NOW)
    assert result.workbook_path is None
    assert not any(line.startswith("Wrote ") for line in lines)
    assert any("No workbook written" in line for line in lines)


def test_config_warnings_are_logged(cfg, browser, monkeypatch):
    import dataclasses

    monkeypatch.setattr(job, "run", fake_run)
    lines = []
    execute(dataclasses.replace(cfg, warnings=("Warning: old key",)), ["/a"], lines.append, confirmed,
            session_factory=browser, now=lambda: NOW)
    assert lines[0] == "Warning: old key"


def test_missing_ui_steps_file_exit_1(cfg, browser, monkeypatch, tmp_path):
    monkeypatch.setattr(job, "app_dir", lambda: tmp_path)
    lines = []
    result = execute(cfg, ["/a"], lines.append, confirmed, session_factory=browser, now=lambda: NOW)
    assert result.exit_code == 1
    assert any("UI steps file not found" in line for line in lines)


class FakeFetcher:
    def __init__(self, cfg, steps, page, log, error=None):
        self.page = self
        self.error = error

    def run_search(self, query, earliest, latest):
        if self.error:
            raise self.error
        return [{"sessionId": "s1", "_time": "t"}]

    def selector_report(self):
        return ["  results.done: 1 match(es), visible  [#done]"]

    def screenshot(self, path, full_page):
        open(path, "wb").close()


def test_probe_reports_columns_selectors_and_screenshot(cfg, browser, monkeypatch):
    monkeypatch.setattr(job, "UiFetcher", FakeFetcher)
    lines = []
    result = execute(cfg, ["/a", "/b"], lines.append, confirmed, session_factory=browser, now=lambda: NOW, probe=True)
    assert result.exit_code == 0 and result.workbook_path is None
    assert "UI steps OK: 1 row(s); columns: sessionId, _time" in lines
    assert "  results.done: 1 match(es), visible  [#done]" in lines
    shot = result.log_path.with_name("api_sequence_20261019_093000_probe.png")
    assert shot.exists() and f"Screenshot: {shot}" in lines


def test_probe_failure_exit_1_with_reason(cfg, browser, monkeypatch):
    from splunk_seq.errors import SearchError

    monkeypatch.setattr(job, "UiFetcher", lambda *a: FakeFetcher(*a, error=SearchError("no table")))
    lines = []
    result = execute(cfg, ["/a"], lines.append, confirmed, session_factory=browser, now=lambda: NOW, probe=True)
    assert result.exit_code == 1
    assert "UI steps failed: no table" in lines
