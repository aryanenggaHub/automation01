# Standalone App — Design Spec

Status: approved design, not yet built. Builds on [the v1 spec](2026-10-17-splunk-api-sequence-design.md); vocabulary in [GLOSSARY.md](../../../GLOSSARY.md); packaging decision in [ADR 0002](../../adr/0002-standalone-exe-with-tkinter-ui.md).

## 1. Purpose

Let a non-Python user on a locked-down company laptop run the tool: download a zip, unzip, double-click `SplunkSequence.exe`, paste Input APIs, fill in settings in a window, press Run. No Python, no `pip`, no browser download. All Splunk, query, flag and workbook behaviour from v1 is unchanged.

## 2. Out of scope

- Code signing, installers, auto-update.
- macOS/Linux builds.
- UI-scrape fallback (still v1 Task 8, built only if the proxy is blocked).

## 3. Distribution

- GitHub Actions workflow `.github/workflows/release.yml`, triggered **only by pushing a tag `v*`**, on `windows-latest`, Python 3.12:
  1. `pip install -r requirements-dev.txt pyinstaller`, run `python -m pytest -q` (fail → no release).
  2. PyInstaller **one-folder, windowed** build named `SplunkSequence` from entry script `app.py` (repo root). The Playwright driver (Node + package) must be bundled; verify via §3 self-test, not by assumption.
  3. Copy `config.example.yaml` and `README.md` into `dist/SplunkSequence/`.
  4. **Self-test**: run `dist/SplunkSequence/SplunkSequence.exe --selftest`; it must exit 0 and write `selftest.ok` next to the exe after confirming `import playwright` works and the bundled driver executable exists. Fail the job otherwise.
  5. Zip `dist/SplunkSequence/` as `SplunkSequence-<tag>-windows.zip` and create a GitHub Release for the tag with that asset (`gh release create`, `permissions: contents: write`).
- `splunk_seq/__init__.py` holds `__version__ = "1.0.0"`; window title shows it. First release tag: `v1.0.0`.

## 4. App folder layout (after unzip)

```
SplunkSequence\
  SplunkSequence.exe
  _internal\            (PyInstaller runtime, incl. Playwright driver)
  config.example.yaml
  README.md
  config.yaml           (created on first Save)
  browser-profile\      (created on first Run)
  output\               (workbooks + logs)
```

**App directory** = folder of the exe when frozen (`sys.frozen`), else the current working directory. `config.yaml`, `browser-profile\`, and relative `output.dir` resolve against it.

## 5. Config changes

- `browser.channel`: default becomes **`chrome`**; allowed values `chrome`, `msedge` (anything else → ConfigError naming the key).
- New `browser.ca_cert_file`: optional path to a `.pem` file; default empty. If set and the file does not exist → ConfigError naming the key.
- Config loading is split so the UI can validate a dict without a file: `parse_config(raw: dict) -> Config` holds all validation; `load_config(path)` reads YAML and calls it.
- `save_config(path, raw)` validates via `parse_config` **first**, then writes YAML (`sort_keys=False`). Invalid → ConfigError, file untouched. Comments in a hand-edited `config.yaml` are not preserved (accepted).
- First launch (no `config.yaml`): the form is filled from the bundled `config.example.yaml` with `splunk.url` blanked.
- `config.example.yaml` gains `browser.channel: chrome` and a commented `ca_cert_file: ""`.

## 6. Browser session changes (CLI and app alike)

- Launch with `chromium.launch_persistent_context(user_data_dir=<app dir>/browser-profile, channel=..., headless=False, ignore_https_errors=...)`; use its first page (or a new one) to open `splunk.url`.
- If `ca_cert_file` is set, set environment variable `NODE_EXTRA_CA_CERTS` to its absolute path **before** starting Playwright (the driver reads it at start).
- Login wait also ends early (returns not-logged-in) when the user presses Stop.

## 7. Shared run job

One function used by both the CLI and the window, so they cannot drift:

`execute(cfg, apis, log, should_stop) -> JobResult` where `JobResult` carries `exit_code` (0 / 2 as in v1 §4), `workbook_path`, `log_path`, `tally`.

- Opens the browser session, waits for login, builds the proxy search with re-login, runs all APIs, closes the browser.
- Writes every log line to the window/console **and** to `<output dir>/<workbook stem>.log` (UTF-8), created alongside the workbook.
- `run()` gains `should_stop: Callable[[], bool]`, checked before each Input API; when true it logs `Stopped by user after <n> of <total> APIs` and returns the tally so far. The workbook already holds everything processed.

## 8. Window (tkinter, `splunk_seq/gui.py`)

Title `Splunk API Sequence v<version>`. Top to bottom:

1. **Input APIs**: multi-line text box (one endpoint per line, `#` comments allowed; parsed with the existing `load_input_apis`) and a **Load file…** button that replaces the box contents with a chosen `.txt` (read as `utf-8-sig`).
2. **Main settings**: Browser (Chrome / Edge dropdown), Splunk URL, Earliest, Latest, Sessions per API, Session Query (multi-line), Sequence Query (multi-line), Output folder (entry + Browse…).
3. **Advanced** (collapsed by default, toggle button): Session ID field, Timestamp field, Timestamp format, Ambiguity window (ms), the four Layer column names (Gateway, Microservice, Downstream API, Downstream MQ), Company CA certificate (.pem) (entry + Browse…), Ignore HTTPS errors (checkbox).
4. **Buttons**: Save, Run, Stop, Open output folder.
5. **Log pane**: read-only, auto-scrolling.

Behaviour:
- **Save**: build the raw dict from the form, `save_config`; on ConfigError show an error dialog with its message; on success a short status line.
- **Run**: Save first (abort on error); abort with a dialog if the Input API box yields no APIs; disable Run and form editing, enable Stop; start `execute` on a **worker thread** (all Playwright calls stay on that thread). Log lines reach the pane through a `queue.Queue` polled with `after(100)`. On finish: re-enable Run, disable Stop, log the tally and workbook path, enable Open output folder.
- **Stop**: sets the stop flag; the button shows "Stopping…" until the worker finishes.
- **Open output folder**: `os.startfile` on the resolved output dir (created if missing).
- Closing the window during a run asks for confirmation, then sets the stop flag and waits for the worker.
- Numeric fields that don't parse as integers are reported by the same Save error dialog (the form passes them through as given; `parse_config` rejects them).

## 9. Entry point

`app.py` (repo root): `--selftest` → self-test (§3 step 4) and exit; otherwise open the window. The CLI (`python -m splunk_seq`) stays and uses `execute` too.

## 10. Testing

Unit-test without a display or browser:
- config: `parse_config` on dicts, channel validation, `ca_cert_file` missing → error, `save_config` refuses invalid input without touching the file, round trip save→load, first-launch defaults (URL blank).
- app dir resolution (frozen vs not) and relative output dir resolution.
- runner: `should_stop` stops before the next API and logs the message.
- job: with a fake browser session, log lines go to both the callback and the `.log` file; exit code 2 on login timeout; `NODE_EXTRA_CA_CERTS` set when `ca_cert_file` given.
- gui: the pure form↔dict mapping (`form_to_raw` / `raw_to_form`) round-trips; tkinter widgets themselves are verified manually.
- self-test function returns success in the dev environment.

Manual checklist (README): exe starts on the company laptop; Chrome opens with the persistent profile and login is remembered on the second run; CA certificate fixes certificate errors; Stop works mid-run; `.log` file appears next to the workbook.

## 11. README

New top section **Download and run** (Releases page, unzip somewhere writable, SmartScreen "More info → Run anyway", `chrome://policy` RemoteDebugging check, installing a sign-in extension into the app's profile), **Company certificate** guide (export root as Base-64 `.pem` from Chrome's padlock → Certificate, pick it under Advanced), and a short **Using the window** section. Existing CLI docs move under "Running from source".
