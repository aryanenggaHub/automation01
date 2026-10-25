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



def test_continue_button_confirms_login(app):
    import threading

    result = []
    worker = threading.Thread(target=lambda: result.append(app._confirm_login(10)))
    worker.start()
    prompt = app.messages.get(timeout=5)
    assert isinstance(prompt, gui.LoginPrompt) and prompt.active
    app.login_event.set()  # what the Continue button does
    worker.join(timeout=5)
    assert result == [True]
    assert app.messages.get(timeout=5).active is False


def test_stop_ends_login_wait(app):
    app.stop_event.set()
    assert app._confirm_login(10) is False
