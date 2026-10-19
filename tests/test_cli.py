import pytest

import splunk_seq.cli as cli
from splunk_seq.cli import load_input_apis, main
from splunk_seq.job import JobResult


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


@pytest.fixture
def captured(monkeypatch):
    seen = {}

    def fake_execute(cfg, apis, log, should_stop=lambda: False):
        seen["apis"] = apis
        seen["cfg"] = cfg
        return JobResult(seen.get("exit_code", 0), None, None, {"OK": len(apis), "NO_SESSION": 0, "ERROR": 0})

    monkeypatch.setattr(cli, "execute", fake_execute)
    return seen


def test_load_input_apis_skips_comments_blanks_and_dedupes():
    assert load_input_apis(" /a \n\n# c\n  # c2\n/b\n/a\n") == (["/a", "/b"], 1)


def test_main_strips_utf8_bom(tmp_path, config_file, captured):
    apis = tmp_path / "apis.txt"
    apis.write_bytes(b"\xef\xbb\xbf/a\n/b\n")
    assert main(["run", "--file", str(apis), "--config", str(config_file)]) == 0
    assert captured["apis"] == ["/a", "/b"]


def test_cli_overrides_time_range(config_file, captured):
    assert main(["run", "--api", "/a", "--config", str(config_file), "--earliest=-1h"]) == 0
    assert captured["cfg"].search.earliest == "-1h"


def test_api_and_file_mutually_exclusive(config_file):
    assert main(["run", "--api", "/a", "--file", "x", "--config", str(config_file)]) == 1


def test_missing_config_returns_1(tmp_path):
    assert main(["run", "--api", "/a", "--config", str(tmp_path / "nope.yaml")]) == 1


def test_missing_input_file_returns_1(tmp_path, config_file, captured):
    assert main(["run", "--file", str(tmp_path / "nope.txt"), "--config", str(config_file)]) == 1


def test_exit_code_comes_from_job(config_file, captured):
    captured["exit_code"] = 2
    assert main(["run", "--api", "/a", "--config", str(config_file)]) == 2
