import sys
from pathlib import Path

from splunk_seq.paths import app_dir, resolve_in_app


def test_app_dir_is_cwd_when_not_frozen(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert app_dir() == tmp_path


def test_app_dir_is_exe_folder_when_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "SplunkSequence.exe"))
    assert app_dir() == tmp_path


def test_resolve_in_app_keeps_absolute(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    absolute = tmp_path / "elsewhere" / "x.pem"
    assert resolve_in_app(absolute) == absolute
    assert resolve_in_app("output") == tmp_path / "output"
