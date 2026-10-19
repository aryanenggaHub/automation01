import tkinter as tk
from pathlib import Path

import pytest

import splunk_seq.gui as gui


@pytest.fixture(scope="module")
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def app(tk_root, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    errors = []
    monkeypatch.setattr(gui.messagebox, "showerror", lambda title, msg: errors.append((title, msg)))
    monkeypatch.setattr(gui, "example_path", lambda: Path(__file__).parent.parent / "config.example.yaml")
    window = tk.Toplevel(tk_root)
    application = gui.App(window)
    application.errors = errors
    yield application
    window.destroy()


def test_load_file_with_wrong_encoding_shows_dialog(app, tmp_path, monkeypatch):
    f = tmp_path / "apis.txt"
    f.write_bytes("/a\n".encode("utf-16"))
    monkeypatch.setattr(gui.filedialog, "askopenfilename", lambda **kw: str(f))
    app.load_file()
    assert app.errors and app.errors[-1][0] == "Load file"


def test_open_output_failure_shows_dialog(app, monkeypatch):
    def deny(path):
        raise OSError("no association")

    monkeypatch.setattr(gui.os, "startfile", deny)
    app.open_output()
    assert app.errors and app.errors[-1][0] == "Open output folder"


def test_worker_crash_reports_traceback(app, monkeypatch):
    def boom(*args, **kwargs):
        raise ValueError("kaboom")

    monkeypatch.setattr(gui, "execute", boom)
    app._work(None, ["/a"])
    lines = []
    while not app.messages.empty():
        lines.append(app.messages.get())
    text = "\n".join(str(x) for x in lines)
    assert "Traceback" in text and "kaboom" in text
