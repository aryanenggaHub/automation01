import pytest

import splunk_seq.cli as cli
from splunk_seq.cli import load_input_apis, main


@pytest.fixture
def config_file(tmp_path):
    p = tmp_path / "config.yaml"
    out = (tmp_path / "out").as_posix()
    p.write_text(
        'splunk: {url: "https://splunk.local:8000"}\n'
        "session: {query: x}\n"
        "sequence: {query: y}\n"
        f"output: {{dir: '{out}'}}\n",
        encoding="utf-8",
    )
    return p


class FakeBrowser:
    logged_in = True

    def __init__(self, cfg):
        self.page = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def wait_for_login(self):
        return self.logged_in

    def post(self, url, form, headers, timeout_s):
        return 200, "application/json", ""

    def cookies(self):
        return []


@pytest.fixture
def captured(monkeypatch):
    seen = {}

    def fake_run(apis, cfg, search, workbook, log=print):
        seen["apis"] = apis
        seen["cfg"] = cfg
        return {"OK": len(apis), "NO_SESSION": 0, "ERROR": 0}

    monkeypatch.setattr(cli, "BrowserSession", FakeBrowser)
    monkeypatch.setattr(cli, "run", fake_run)
    return seen


def test_load_input_apis_skips_comments_blanks_and_dedupes():
    assert load_input_apis(" /a \n\n# c\n  # c2\n/b\n/a\n") == (["/a", "/b"], ["/a"])


def test_main_strips_utf8_bom(tmp_path, config_file, captured):
    apis = tmp_path / "apis.txt"
    apis.write_bytes(b"\xef\xbb\xbf/a\n/b\n")
    assert main(["run", "--file", str(apis), "--config", str(config_file)]) == 0
    assert captured["apis"] == ["/a", "/b"]


def test_cli_overrides_time_range(config_file, captured):
    assert main(["run", "--api", "/a", "--config", str(config_file), "--earliest", "-1h"]) == 0
    assert captured["cfg"].search.earliest == "-1h"


def test_api_and_file_mutually_exclusive(config_file):
    assert main(["run", "--api", "/a", "--file", "x", "--config", str(config_file)]) == 1


def test_missing_config_returns_1(tmp_path):
    assert main(["run", "--api", "/a", "--config", str(tmp_path / "nope.yaml")]) == 1


def test_missing_input_file_returns_1(tmp_path, config_file, captured):
    assert main(["run", "--file", str(tmp_path / "nope.txt"), "--config", str(config_file)]) == 1


def test_login_timeout_returns_2(config_file, captured, monkeypatch):
    monkeypatch.setattr(FakeBrowser, "logged_in", False)
    assert main(["run", "--api", "/a", "--config", str(config_file)]) == 2
