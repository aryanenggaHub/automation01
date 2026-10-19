# Standalone App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the tool as a zipped one-folder Windows exe with a tkinter window, built by GitHub Actions on version tags, so it runs on a laptop with no Python.

**Architecture:** Pull the CLI's run flow into one `execute()` job shared by the CLI and the window; the window is a thin tkinter shell over a pure form↔config-dict mapping and a worker thread. The browser switches to a persistent profile beside the exe and can trust a company CA via `NODE_EXTRA_CA_CERTS`. PyInstaller packages it; a `--selftest` flag proves the Playwright driver is bundled before any release.

**Tech Stack:** Python 3.12, tkinter (stdlib), playwright (sync), openpyxl, pyyaml, PyInstaller, GitHub Actions (`windows-latest`, `gh release create`).

**Spec:** [docs/superpowers/specs/2026-10-19-standalone-app-design.md](../specs/2026-10-19-standalone-app-design.md) (extends [the v1 spec](../specs/2026-10-17-splunk-api-sequence-design.md)); decision in [ADR 0002](../../adr/0002-standalone-exe-with-tkinter-ui.md).

## Global Constraints

- No new runtime dependencies; UI is tkinter only. PyInstaller is build-only.
- Windows, one-folder windowed build named `SplunkSequence`; release asset `SplunkSequence-<tag>-windows.zip`; releases only on tags `v*`.
- `__version__ = "1.0.0"` in `splunk_seq/__init__.py`; window title `Splunk API Sequence v<version>`.
- App dir = exe folder when `sys.frozen`, else current working directory; `config.yaml`, `browser-profile`, relative `output.dir`, and relative `browser.ca_cert_file` resolve against it.
- `browser.channel` ∈ {`chrome`, `msedge`}, default `chrome`. `browser.ca_cert_file` default `""`.
- Browser always visible, persistent profile at `<app dir>/browser-profile`.
- All Playwright calls stay on the worker thread that created the session.
- v1 behaviour (queries, flags, workbook, exit codes 0/1/2) unchanged.
- Run commands with `.venv/Scripts/python` (the `python` on PATH is a Store stub).

## Review Focus

1. **Browser fails to start** (Chrome not installed, or `browser-profile` locked by a Chrome window left open from an earlier run) → logged "Could not start the browser: …" and exit code 1, not a crash/traceback. Test in Task 4.
2. **Hand-edited `config.yaml` that is invalid or not even YAML** at launch → window still opens (invalid values shown, or example defaults with a warning); the error surfaces on Save. Test in Task 1.
3. **App unzipped into a read-only folder** → Save shows an error dialog (ConfigError), no traceback. Test in Task 1.
4. **Stop pressed while waiting for login** → run ends promptly, logs "Stopped", writes no workbook. Test in Task 4.
5. **Relative `ca_cert_file` or one with spaces in its path** → resolved to an absolute path against the app dir before being exported. Test in Task 3.

---

## File Structure

```
app.py                     # NEW entry: --selftest or open window
splunk_seq/
  __init__.py              # + __version__
  paths.py                 # NEW app_dir, resolve_in_app
  config.py                # parse_config / load_config / save_config / load_raw_or_default; channel + ca_cert_file
  browser.py               # persistent profile, ca env, wait_until should_stop
  runner.py                # run(..., should_stop)
  workbook.py              # output_path(..., base)
  job.py                   # NEW execute() + JobResult, log tee
  cli.py                   # uses execute()
  form.py                  # NEW pure form <-> raw dict mapping
  gui.py                   # NEW tkinter window
  selftest.py              # NEW run_selftest
.github/workflows/release.yml   # NEW
config.example.yaml, README.md  # updated
```

---

### Task 1: Paths and config split

**Files:**
- Create: `splunk_seq/paths.py`, `tests/test_paths.py`
- Modify: `splunk_seq/config.py`, `config.example.yaml`, `tests/test_config.py`

**Interfaces:**
- Produces:
  - `paths.app_dir() -> Path`; `paths.resolve_in_app(p: str | Path) -> Path` (absolute paths returned unchanged)
  - `config.parse_config(raw: dict) -> Config` (all validation moves here); `load_config(path)` = read YAML + `parse_config`
  - `config.save_config(path: Path, raw: dict) -> Config` — validates first, then writes YAML (`sort_keys=False`, `allow_unicode=True`); `OSError` on write → `ConfigError("Cannot save config to <path>: <reason>")`
  - `config.load_raw_or_default(path: Path, example: Path) -> tuple[dict, str | None]` — raw dict from `path` if it is a YAML mapping (no validation); else example's dict with `splunk.url` set to `""`, plus a warning string when `path` existed but was unreadable/not a mapping (None when it simply didn't exist)
  - `BrowserCfg(channel: str, ignore_https_errors: bool, ca_cert_file: str)`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_paths.py
def test_app_dir_is_cwd_when_not_frozen(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path); monkeypatch.delattr(sys, "frozen", raising=False)
    assert app_dir() == tmp_path
def test_app_dir_is_exe_folder_when_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "SplunkSequence.exe"))
    assert app_dir() == tmp_path
def test_resolve_in_app_keeps_absolute(): ...      # absolute path unchanged; "output" → app_dir()/"output"

# tests/test_config.py (add; update default assertions: channel == "chrome", ca_cert_file == "")
def test_parse_config_accepts_dict(): ...           # parse_config(yaml.safe_load(MIN)) works without a file
def test_invalid_channel_rejected(): ...            # "firefox" → ConfigError match="browser.channel"
def test_missing_ca_cert_file_rejected(tmp_path): ...  # ca_cert_file: "nope.pem" → match="browser.ca_cert_file"
def test_save_config_round_trip(tmp_path): ...      # save_config(p, raw); load_config(p) == parse_config(raw)
def test_save_config_invalid_leaves_file_untouched(tmp_path): ...  # existing file bytes unchanged after ConfigError
def test_save_config_unwritable_raises_config_error(tmp_path, monkeypatch): ...  # Review Focus 3: Path.write_text raising PermissionError → ConfigError match="Cannot save config"
def test_load_raw_or_default_missing_file(tmp_path): ...   # example used, raw["splunk"]["url"] == "", warning is None
def test_load_raw_or_default_invalid_values_kept(tmp_path): ...  # Review Focus 2: sessions_per_api: "ten" comes back as-is, warning None
def test_load_raw_or_default_broken_yaml(tmp_path): ...    # Review Focus 2: "a: [" → example dict + warning mentioning config.yaml
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_paths.py tests/test_config.py -q` — Expected: FAIL (`paths` module missing; new names undefined).

- [ ] **Step 3: Implement `paths.py` and the config changes**

`ca_cert_file` validated only when non-empty, checked with `resolve_in_app(value).is_file()`. `config.example.yaml`: set `browser.channel: chrome` (comment `chrome | msedge`) and add `ca_cert_file: ""` with a one-line comment.

- [ ] **Step 4: Run the full suite**

Run: `.venv/Scripts/python -m pytest -q` — Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add splunk_seq/paths.py splunk_seq/config.py config.example.yaml tests/test_paths.py tests/test_config.py
git commit -m "feat: app dir paths, parse/save config, chrome default and CA cert setting"
```

---

### Task 2: Stop support in runner and login wait

**Files:**
- Modify: `splunk_seq/runner.py`, `splunk_seq/browser.py` (`wait_until` only), `tests/test_runner.py`, `tests/test_browser.py`

**Interfaces:**
- Produces:
  - `run(apis, cfg, search, workbook, log=print, should_stop: Callable[[], bool] = lambda: False) -> dict[str, int]`
  - `wait_until(check, timeout_s, interval_s=2.0, sleep=..., clock=..., on_error=None, should_stop: Callable[[], bool] = lambda: False) -> bool` — returns False as soon as `should_stop()` is true (checked before each `check()`)

- [ ] **Step 1: Write the failing tests**

```python
def test_should_stop_before_next_api(cfg):          # test_runner.py
    calls = iter([False, True])
    logs, wb = [], FakeWorkbook()
    tally = run(["/a", "/b", "/c"], cfg, FakeSearch({"/a": [], "/b": [], "/c": []}, {}), wb,
                log=logs.append, should_stop=lambda: next(calls))
    assert [i for i, _ in wb.added] == [1]
    assert "Stopped by user after 1 of 3 APIs" in logs
    assert tally == {"OK": 0, "NO_SESSION": 1, "ERROR": 0}

def test_wait_until_returns_false_when_stopped():   # test_browser.py
    fake = FakeClock()
    assert wait_until(lambda: False, 100, 2.0, fake.sleep, fake.clock, should_stop=lambda: True) is False
    assert fake.sleeps == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_runner.py tests/test_browser.py -q` — Expected: FAIL (unexpected keyword `should_stop`).

- [ ] **Step 3: Implement** — `run` checks `should_stop()` at the top of each loop iteration; the stop message counts APIs already processed.

- [ ] **Step 4: Run the full suite** — `.venv/Scripts/python -m pytest -q` — Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add splunk_seq/runner.py splunk_seq/browser.py tests/test_runner.py tests/test_browser.py
git commit -m "feat: stop flag for runs and login wait"
```

---

### Task 3: Persistent browser profile and CA certificate

**Files:**
- Modify: `splunk_seq/browser.py`, `tests/test_browser.py`

**Interfaces:**
- Consumes: `resolve_in_app`, `app_dir` (Task 1); `wait_until(should_stop=...)` (Task 2)
- Produces:
  - `ca_cert_env(cfg: Config) -> dict[str, str]` — `{}` when `ca_cert_file` empty, else `{"NODE_EXTRA_CA_CERTS": str(resolve_in_app(cfg.browser.ca_cert_file))}`
  - `BrowserSession(cfg: Config, should_stop: Callable[[], bool] = lambda: False)`; `wait_for_login() -> bool` passes `should_stop` to `wait_until`; `post`, `cookies()` unchanged

- [ ] **Step 1: Write the failing tests**

```python
def test_ca_cert_env_empty_when_unset(cfg): assert ca_cert_env(cfg) == {}
def test_ca_cert_env_resolves_relative_path_with_spaces(tmp_path, monkeypatch):   # Review Focus 5
    # cwd = tmp_path; file "certs/My Corp CA.pem" exists; ca_cert_file set to that relative path
    assert ca_cert_env(cfg) == {"NODE_EXTRA_CA_CERTS": str(tmp_path / "certs" / "My Corp CA.pem")}
```

- [ ] **Step 2: Run to verify they fail** — `.venv/Scripts/python -m pytest tests/test_browser.py -q` — Expected: FAIL (`ca_cert_env` undefined).

- [ ] **Step 3: Implement**

`__enter__`: `os.environ.update(ca_cert_env(cfg))` before `sync_playwright().start()`; then `self.context = playwright.chromium.launch_persistent_context(str(app_dir() / "browser-profile"), channel=..., headless=False, ignore_https_errors=...)`; `self.page = self.context.pages[0] if self.context.pages else self.context.new_page()`; `goto` url. `__exit__` closes the context and stops Playwright (no separate `Browser` object any more).

- [ ] **Step 4: Run the full suite** — `.venv/Scripts/python -m pytest -q` — Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add splunk_seq/browser.py tests/test_browser.py
git commit -m "feat: persistent browser profile and company CA certificate"
```

---

### Task 4: Shared run job; CLI uses it

**Files:**
- Create: `splunk_seq/job.py`, `tests/test_job.py`
- Modify: `splunk_seq/workbook.py` (`output_path`), `splunk_seq/cli.py`, `tests/test_workbook.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `BrowserSession(cfg, should_stop)` (Task 3); `run(..., should_stop)` (Task 2); `app_dir` (Task 1); `ProxyFetcher`, `with_relogin`, `SequenceWorkbook`
- Produces:
  - `output_path(cfg: OutputCfg, now: datetime, base: Path = Path(".")) -> Path` — `resolve`d against `base` when `cfg.dir` is relative
  - `@dataclass JobResult(exit_code: int, workbook_path: Path | None, log_path: Path | None, tally: dict[str, int])`
  - `execute(cfg: Config, apis: list[str], log: Callable[[str], None], should_stop: Callable[[], bool] = lambda: False, session_factory=BrowserSession, now: Callable[[], datetime] = datetime.now) -> JobResult`

- [ ] **Step 1: Write the failing tests**

Fake session factory = the `FakeBrowser` pattern from `tests/test_cli.py` (move it to `tests/conftest.py` so both files use it), with a `start_error` class attribute raised from `__enter__`.

```python
def test_output_path_relative_to_base(): ...   # output_path(OutputCfg("output","p"), dt, Path("C:/app")) == Path("C:/app/output/p_<stamp>.xlsx")
def test_execute_tees_log_to_file(cfg, tmp_path, monkeypatch): ...
    # monkeypatch splunk_seq.job.run with a fake that logs "hello" via its log arg
    # result.exit_code == 0; "hello" in callback lines; "hello" in result.log_path.read_text("utf-8");
    # result.log_path == result.workbook_path.with_suffix(".log")
def test_execute_login_timeout_exit_2(cfg): ...           # FakeBrowser.logged_in False → exit_code 2, workbook_path None
def test_execute_browser_start_failure_exit_1(cfg): ...   # Review Focus 1: start_error=RuntimeError("profile in use") → exit_code 1, log contains "Could not start the browser: profile in use"
def test_execute_stop_during_login_writes_nothing(cfg): ...  # Review Focus 4: should_stop=lambda: True, logged_in False → log contains "Stopped", workbook_path None, no files in output dir
```

Update `tests/test_cli.py` so `main` is tested against a monkeypatched `cli.execute` (assert it receives the parsed APIs and overridden cfg; exit code is `JobResult.exit_code`).

- [ ] **Step 2: Run to verify they fail** — `.venv/Scripts/python -m pytest tests/test_job.py tests/test_workbook.py tests/test_cli.py -q` — Expected: FAIL (`splunk_seq.job` missing).

- [ ] **Step 3: Implement `job.py`, adjust `output_path`, slim `cli.main`**

`execute`: wrap `session_factory(cfg, should_stop)` enter in `try/except Exception` → log `Could not start the browser: <exc>`, return exit 1. Login false → log `Stopped` if `should_stop()` else `Login was not detected in time`, return exit 2 with no paths. Otherwise compute the workbook path with `base=app_dir()`, open the `.log` beside it (UTF-8, `mkdir(parents=True)`), and use a `tee(line)` that calls `log` and writes+flushes the file; run; finish with `Wrote <path>` and the tally line. `cli.main` keeps parsing/validation and replaces its browser block with `execute(cfg, apis, print).exit_code`.

- [ ] **Step 4: Run the full suite** — `.venv/Scripts/python -m pytest -q` — Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add splunk_seq/job.py splunk_seq/workbook.py splunk_seq/cli.py tests/conftest.py tests/test_job.py tests/test_workbook.py tests/test_cli.py
git commit -m "feat: shared run job with log file, used by CLI"
```

---

### Task 5: Form mapping and tkinter window

**Files:**
- Create: `splunk_seq/form.py`, `splunk_seq/gui.py`, `tests/test_form.py`
- Modify: `splunk_seq/__init__.py`

**Interfaces:**
- Consumes: `load_raw_or_default`, `save_config`, `ConfigError` (Task 1); `execute`, `JobResult` (Task 4); `load_input_apis` (cli); `app_dir`, `resolve_in_app`
- Produces:
  - `form.FIELDS: list[Field]` with `@dataclass(frozen=True) Field(key: str, label: str, kind: str, advanced: bool)`; `kind` ∈ `text`, `multiline`, `int`, `bool`, `choice`, `file`, `dir`; `key` is a dotted path into the raw dict (layer columns: `sequence.layer_columns.Gateway`, etc.)
  - `form.raw_to_form(raw: dict) -> dict[str, str | bool]`; `form.form_to_raw(values: dict[str, str | bool], base: dict) -> dict` — copies `base`, sets each key; `int` fields become `int` when `str.strip().isdigit()`, else stay the given string (so `parse_config` reports them)
  - `gui.main() -> None`
  - `splunk_seq.__version__ = "1.0.0"`

FIELDS, in this order (labels exact): Main — `browser.channel` "Browser" (choice: Chrome→`chrome`, Edge→`msedge`), `splunk.url` "Splunk URL", `search.earliest` "Earliest", `search.latest` "Latest", `session.sessions_per_api` "Sessions per API" (int), `session.query` "Session Query" (multiline), `sequence.query` "Sequence Query" (multiline), `output.dir` "Output folder" (dir). Advanced — `session.session_id_field` "Session ID field", `sequence.timestamp_field` "Timestamp field", `sequence.timestamp_format` "Timestamp format", `sequence.ambiguity_window_ms` "Ambiguity window (ms)" (int), `sequence.layer_columns.Gateway` "Gateway column", `…Microservice` "Microservice column", `…Downstream API` "Downstream API column", `…Downstream MQ` "Downstream MQ column", `browser.ca_cert_file` "Company CA certificate (.pem)" (file), `browser.ignore_https_errors` "Ignore HTTPS errors" (bool).

- [ ] **Step 1: Write the failing tests**

```python
def test_round_trip_example_config():
    raw = yaml.safe_load(Path("config.example.yaml").read_text("utf-8"))
    assert form_to_raw(raw_to_form(raw), raw) == raw
def test_int_fields_converted_or_left_for_validation():
    out = form_to_raw({**raw_to_form(raw), "session.sessions_per_api": " 5 ", "sequence.ambiguity_window_ms": "abc"}, raw)
    assert out["session"]["sessions_per_api"] == 5 and out["sequence"]["ambiguity_window_ms"] == "abc"
def test_missing_sections_created(): ...      # form_to_raw on base={} builds nested dicts incl. layer_columns
def test_every_field_key_present_in_example(): ...  # each FIELDS key resolves in the example raw dict
```

- [ ] **Step 2: Run to verify they fail** — `.venv/Scripts/python -m pytest tests/test_form.py -q` — Expected: FAIL (module missing).

- [ ] **Step 3: Implement `form.py`**, then **Step 4: run** `.venv/Scripts/python -m pytest -q` — Expected: all PASS.

- [ ] **Step 5: Implement `gui.py`** per spec §8

Layout with `ttk` widgets in a scrollable main frame; Advanced frame packed/unpacked by a toggle button. Startup: `load_raw_or_default(app_dir()/"config.yaml", <example path>)` — example path is `app_dir()/"config.example.yaml"`, falling back to `Path(sys._MEIPASS)/"config.example.yaml"` when frozen; show the warning (if any) in the log pane. Worker: `threading.Thread(target=..., daemon=True)` calling `execute(cfg, apis, queue.put, stop_event.is_set)`; poll the queue with `after(100)`; a sentinel tuple signals completion with the `JobResult`. Close during run: `askyesno`, set stop, keep polling until the worker ends, then `destroy`.

- [ ] **Step 6: Manual check** — `.venv/Scripts/python -c "from splunk_seq.gui import main; main()"`: window opens with example values, Advanced toggles, Save with an empty URL shows the `splunk.url` error dialog, Load file… fills the box, Run with an empty box shows the "no Input APIs" dialog. Close the window.

- [ ] **Step 7: Commit**

```bash
git add splunk_seq/form.py splunk_seq/gui.py splunk_seq/__init__.py tests/test_form.py
git commit -m "feat: tkinter window over a pure form mapping"
```

---

### Task 6: Entry point, self-test, local exe build

**Files:**
- Create: `app.py`, `splunk_seq/selftest.py`, `tests/test_selftest.py`, `build.ps1`
- Modify: `.gitignore` (`build/`, `dist/`, `*.spec`)

**Interfaces:**
- Produces: `selftest.run_selftest(out_dir: Path) -> bool` — imports `playwright.sync_api`, checks the bundled driver executable from `playwright._impl._driver.compute_driver_executable()` exists (it returns a tuple of paths in recent versions: every path must exist), writes `out_dir/"selftest.ok"` on success; never raises (returns False)

- [ ] **Step 1: Write the failing test** — `test_selftest_passes_in_dev(tmp_path)`: `run_selftest(tmp_path) is True and (tmp_path/"selftest.ok").exists()`.
- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_selftest.py -q` — Expected: FAIL (module missing).
- [ ] **Step 3: Implement `selftest.py` and `app.py`** — `app.py`: if `"--selftest" in sys.argv`: `raise SystemExit(0 if run_selftest(app_dir()) else 1)`; else `gui.main()`.
- [ ] **Step 4: Run** the full suite — Expected: all PASS.
- [ ] **Step 5: Write `build.ps1`** (used by CI and locally): `pyinstaller --noconfirm --clean --windowed --name SplunkSequence --collect-all playwright app.py`, then copy `config.example.yaml` and `README.md` into `dist/SplunkSequence/`.
- [ ] **Step 6: Build and self-test locally**

Run: `.venv/Scripts/python -m pip install pyinstaller`, then `powershell -File build.ps1` with the venv's Scripts on PATH, then `dist/SplunkSequence/SplunkSequence.exe --selftest; echo $?` (use `Start-Process -Wait -PassThru` since the exe is windowed).
Expected: exit code 0 and `dist/SplunkSequence/selftest.ok` exists. If it fails, the driver is not bundled — fix the PyInstaller flags before continuing.

- [ ] **Step 7: Commit**

```bash
git add app.py splunk_seq/selftest.py tests/test_selftest.py build.ps1 .gitignore
git commit -m "feat: exe entry point, self-test, PyInstaller build script"
```

---

### Task 7: Release workflow and README

**Files:**
- Create: `.github/workflows/release.yml`
- Modify: `README.md`

- [ ] **Step 1: Write `release.yml`** per spec §3: `on: push: tags: ["v*"]`; `permissions: contents: write`; `runs-on: windows-latest`; steps: checkout, `actions/setup-python@v5` 3.12, `pip install -r requirements-dev.txt pyinstaller`, `python -m pytest -q`, `pwsh -File build.ps1`, self-test (`Start-Process ... -Wait -PassThru`, fail unless ExitCode 0 and `selftest.ok` exists; then delete `selftest.ok`), `Compress-Archive dist/SplunkSequence "SplunkSequence-${{ github.ref_name }}-windows.zip"`, `gh release create ${{ github.ref_name }} <zip> --title ${{ github.ref_name }} --generate-notes` with `GH_TOKEN: ${{ github.token }}`.
- [ ] **Step 2: Validate the YAML** — `.venv/Scripts/python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/release.yml')); print('ok')"` — Expected: `ok`.
- [ ] **Step 3: Rewrite README** per spec §11: new top sections **Download and run**, **Using the window**, **Company certificate**; manual checklist from spec §10; existing CLI material under **Running from source** (note `--earliest=-1h` form still applies).
- [ ] **Step 4: Run the full suite** — `.venv/Scripts/python -m pytest -q` — Expected: all PASS.
- [ ] **Step 5: Commit**

```bash
git add .github/workflows/release.yml README.md
git commit -m "ci: tagged Windows release build; README for the app"
```

Tagging `v1.0.0` (which triggers the release) happens after the final review, at finish time.
