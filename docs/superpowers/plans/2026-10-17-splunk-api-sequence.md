# Splunk API Sequence Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Python CLI that, for each Input API, finds its Sessions in Splunk Enterprise, pulls each Session's API Sequence, flags Ambiguous calls, and writes an indexed Excel workbook.

**Architecture:** Pure, unit-tested core (config, query templating, flagging, workbook, export parsing, run orchestration) behind one search function shape `SearchFn = Callable[[str, str, str], list[Row]]`. A thin Playwright layer supplies login and an authenticated HTTP `post`; it is the only part verified manually inside the target network.

**Tech Stack:** Python 3.10+, playwright (sync API), openpyxl, pyyaml, pytest.

**Spec:** [docs/superpowers/specs/2026-10-17-splunk-api-sequence-design.md](../specs/2026-10-17-splunk-api-sequence-design.md). Vocabulary: [GLOSSARY.md](../../../GLOSSARY.md). Decision record: [ADR 0001](../../adr/0001-browser-login-with-splunkd-web-proxy.md).

## Global Constraints

- Python 3.10+; runtime deps only `playwright`, `openpyxl`, `pyyaml`; dev adds `pytest`.
- No `playwright install` step; browser launched with `channel` from config (default `msedge`), `headless: false`.
- No environment value hard-coded: Splunk URL, both queries, field names, layer columns all come from `config.yaml`.
- Query templating replaces only the literal tokens `{input_api}` / `{session_id}`; never `str.format`.
- Exit codes: `0` run completed; `1` invalid config, missing input file, or bad CLI usage; `2` login never succeeded.
- Status values exactly `OK`, `NO_SESSION`, `ERROR`. Flag values exactly `UNKNOWN_LAYER`, `BAD_TIMESTAMP`, `AMBIGUOUS`, or empty.
- Output path `{output.dir}/{filename_prefix}_{YYYYMMDD_HHMMSS}.xlsx`; workbook saved after every Input API.
- Index sheet named `Index`; per-API sheet names ≤ 31 chars.
- All tests run offline: `python -m pytest -q` from the repo root.

## Review Focus

1. **Input file saved by Notepad with a UTF-8 BOM** → first API must not start with `﻿`. Test in Task 7.
2. **Log values beginning with `=`, `+`, `-`, `@`** → written as literal text, never as Excel formulas. Test in Task 4.
3. **Log values containing control characters** (openpyxl `IllegalCharacterError`) → characters stripped, row still written. Test in Task 4.
4. **Session Query returns rows but none carry `session_id_field`** (field-name typo in config) → `ERROR` with a message naming the field, not a silent `NO_SESSION`. Test in Task 6.
5. **Endpoint with no alphanumerics** (e.g. `/`) → sheet name is just the numeric prefix, still valid and unique. Test in Task 4.

---

## File Structure

```
splunk_seq/
  __init__.py
  __main__.py      # raise SystemExit(main())
  config.py        # Config dataclasses, load_config, with_overrides
  queries.py       # escape_spl, render_session_query, render_sequence_query
  models.py        # Row, SearchFn, SessionResult, ApiResult, status/flag constants
  flags.py         # compute_flags
  workbook.py      # sheet_name, output_path, SequenceWorkbook
  errors.py        # SearchError, LoginExpired, ProxyUnavailable
  fetch_proxy.py   # parse_export, build_export_request, ProxyFetcher
  fetch.py         # with_relogin, AutoFetcher, UiFetcher (stub until Task 8)
  runner.py        # run
  browser.py       # wait_until, BrowserSession
  cli.py           # load_input_apis, build_parser, main
tests/             # one test_<module>.py per module
config.example.yaml
requirements.txt, requirements-dev.txt, pytest.ini, .gitignore, README.md
```

---

### Task 1: Project scaffold and config

**Files:**
- Create: `splunk_seq/__init__.py` (empty), `splunk_seq/config.py`, `config.example.yaml`, `requirements.txt`, `requirements-dev.txt`, `pytest.ini`, `.gitignore`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  - Frozen dataclasses: `SplunkCfg(url: str, locale: str, login_timeout_seconds: int)`, `BrowserCfg(channel: str, headless: bool)`, `SearchCfg(earliest: str, latest: str, timeout_seconds: int)`, `SessionCfg(query: str, session_id_field: str, sessions_per_api: int)`, `SequenceCfg(query: str, timestamp_field: str, timestamp_format: str, ambiguity_window_ms: int, layer_columns: dict[str, str])`, `OutputCfg(dir: str, filename_prefix: str)`, `Config(splunk, browser, search, fetch_mode: str, session, sequence, output)`.
  - `class ConfigError(Exception)`
  - `load_config(path: Path) -> Config`
  - `with_overrides(cfg: Config, earliest: str | None, latest: str | None) -> Config`

- [ ] **Step 1: Scaffold the repo**

Run `git init`. `requirements.txt`: `playwright`, `openpyxl`, `pyyaml`. `requirements-dev.txt`: `-r requirements.txt` + `pytest`. `pytest.ini`: `[pytest]` / `testpaths = tests` / `pythonpath = .`. `.gitignore`: `__pycache__/`, `.pytest_cache/`, `output/`, `config.yaml`. Then `pip install -r requirements-dev.txt`.

- [ ] **Step 2: Write the failing tests**

```python
MIN = """
splunk: {url: "https://splunk.local:8000/"}
session: {query: 'x "{input_api}"'}
sequence: {query: 'y "{session_id}"'}
"""

def test_minimal_config_gets_spec_defaults(tmp_path):
    cfg = load_config(write(tmp_path, MIN))
    assert cfg.splunk.url == "https://splunk.local:8000"          # trailing slash stripped
    assert cfg.splunk.locale == "en-US" and cfg.splunk.login_timeout_seconds == 300
    assert cfg.browser.channel == "msedge" and cfg.browser.headless is False
    assert (cfg.search.earliest, cfg.search.latest, cfg.search.timeout_seconds) == ("-24h", "now", 300)
    assert cfg.fetch_mode == "auto"
    assert cfg.session.session_id_field == "sessionId" and cfg.session.sessions_per_api == 10
    assert cfg.sequence.timestamp_field == "Timestamp"
    assert cfg.sequence.timestamp_format == "%H:%M:%S.%f"
    assert cfg.sequence.ambiguity_window_ms == 500
    assert cfg.sequence.layer_columns == {
        "Gateway": "Gateway API Endpoint",
        "Microservice": "Microservice Endpoint",
        "Downstream API": "Downstream Integration (API)",
        "Downstream MQ": "Downstream Integration (MQ)",
    }
    assert (cfg.output.dir, cfg.output.filename_prefix) == ("output", "api_sequence")

@pytest.mark.parametrize("key", ["splunk.url", "session.query", "sequence.query"])
def test_missing_required_key_is_named(tmp_path, key): ...   # remove key from MIN; ConfigError match=key

def test_invalid_fetch_mode_rejected(tmp_path): ...          # fetch_mode: fast → ConfigError match="fetch_mode"
def test_non_positive_int_rejected(tmp_path): ...            # session.sessions_per_api: 0 → match="session.sessions_per_api"
def test_non_mapping_yaml_rejected(tmp_path): ...            # "- a\n- b" → ConfigError
def test_overrides_replace_only_given_values(tmp_path):
    cfg = with_overrides(load_config(write(tmp_path, MIN)), "-1h", None)
    assert (cfg.search.earliest, cfg.search.latest) == ("-1h", "now")
def test_example_config_is_valid():
    load_config(Path("config.example.yaml"))
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_config.py -v` — Expected: FAIL (`ModuleNotFoundError: splunk_seq.config`).

- [ ] **Step 4: Implement `splunk_seq/config.py` and `config.example.yaml`**

`load_config` reads with `yaml.safe_load`, validates required keys, `fetch_mode ∈ {auto, proxy, ui}`, and that `login_timeout_seconds`, `timeout_seconds`, `sessions_per_api`, `ambiguity_window_ms` are positive ints; every error message contains the dotted key. `with_overrides` uses `dataclasses.replace`. `config.example.yaml` is the spec §5 block verbatim, with a comment on each key; keep the "Results must come out newest first" comment on `session.query`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py -v` — Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add .
git commit -m "feat: project scaffold and config loading"
```

---

### Task 2: Query templating

**Files:**
- Create: `splunk_seq/queries.py`
- Test: `tests/test_queries.py`

**Interfaces:**
- Consumes: `SessionCfg`, `SequenceCfg` (Task 1)
- Produces: `escape_spl(value: str) -> str`, `render_session_query(cfg: SessionCfg, input_api: str) -> str`, `render_sequence_query(cfg: SequenceCfg, session_id: str) -> str`

- [ ] **Step 1: Write the failing tests**

```python
def test_escape_backslash_then_quote():
    assert escape_spl('a\\b"c') == 'a\\\\b\\"c'

def test_session_query_substitutes_appends_and_prefixes():
    cfg = SessionCfg(query='index=gw "{input_api}" | table _time sessionId', session_id_field="sessionId", sessions_per_api=10)
    assert render_session_query(cfg, "/v1/a") == 'search index=gw "/v1/a" | table _time sessionId | dedup sessionId | head 10'

def test_leading_pipe_or_search_not_prefixed(): ...      # "| tstats ..." and "search index=x" kept as-is (after strip)
def test_other_braces_untouched():
    # sequence template containing rex '(?<f>\d{3})' keeps {3} and replaces {session_id}
def test_input_value_is_escaped(): ...                    # input_api 'a"b' → 'a\\"b' inside the query
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_queries.py -v` — Expected: FAIL (module missing).

- [ ] **Step 3: Implement `splunk_seq/queries.py`**

Plain `str.replace` of the token with `escape_spl(value)`; session suffix ` | dedup {session_id_field} | head {sessions_per_api}`; strip whole query, prefix `search ` unless it starts with `search ` or `|`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_queries.py -v` — Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add splunk_seq/queries.py tests/test_queries.py
git commit -m "feat: SPL query templating"
```

---

### Task 3: Models and flag computation

**Files:**
- Create: `splunk_seq/models.py`, `splunk_seq/flags.py`
- Test: `tests/test_flags.py`

**Interfaces:**
- Consumes: `SequenceCfg` (Task 1)
- Produces (`models.py`):
  - `Row = dict[str, str]`; `SearchFn = Callable[[str, str, str], list[Row]]` (query, earliest, latest)
  - `OK, NO_SESSION, ERROR` status constants; `UNKNOWN_LAYER, BAD_TIMESTAMP, AMBIGUOUS` flag constants (string values equal their names)
  - `@dataclass SessionResult(session_id: str, rows: list[Row], flags: list[str])`
  - `@dataclass ApiResult(input_api: str, status: str, sessions: list[SessionResult] = field(default_factory=list), error: str = "")`
- Produces (`flags.py`): `compute_flags(rows: list[Row], cfg: SequenceCfg) -> list[str]` — one flag per row, same order; `""` for no flag. Called once per Session.

- [ ] **Step 1: Write the failing tests**

Use a helper `r(ts, **layers)` building a row with `Timestamp=ts` and layer column values; `cfg` = defaults from Task 1.

```python
def test_same_layer_within_window_both_ambiguous():
    rows = [r("04:21:01.000", ms="A"), r("04:21:01.400", ms="B")]
    assert compute_flags(rows, cfg) == [AMBIGUOUS, AMBIGUOUS]

def test_window_boundary_inclusive():
    assert compute_flags([r("04:21:01.000", ms="A"), r("04:21:01.500", ms="B")], cfg) == [AMBIGUOUS, AMBIGUOUS]
    assert compute_flags([r("04:21:01.000", ms="A"), r("04:21:01.501", ms="B")], cfg) == ["", ""]

def test_different_layers_never_ambiguous(): ...       # gateway + ms 1 ms apart → ["", ""]
def test_unknown_layer_when_zero_or_two_layers_filled(): ...
def test_unknown_layer_beats_bad_timestamp(): ...      # no layer + "garbage" ts → UNKNOWN_LAYER
def test_bad_timestamp_missing_or_unparseable(): ...
def test_flagged_rows_excluded_from_comparison(): ...  # BAD_TIMESTAMP row between two ms rows 600 ms apart → ["", BAD_TIMESTAMP, ""]
def test_whitespace_only_value_counts_as_empty(): ...
def test_input_order_preserved_when_unsorted(): ...    # rows given out of time order; flags align to input positions
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_flags.py -v` — Expected: FAIL (modules missing).

- [ ] **Step 3: Implement `models.py` and `compute_flags`**

Layer = the single `layer_columns` key whose column value is non-empty after `strip()`. Parse with `datetime.strptime(value, cfg.timestamp_format)`. Group eligible rows by Layer, sort each group by time, and flag both rows of every adjacent pair with `later - earlier <= timedelta(milliseconds=window)` — compare `timedelta`s, not floats, so the 500 ms boundary is exact.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_flags.py -v` — Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add splunk_seq/models.py splunk_seq/flags.py tests/test_flags.py
git commit -m "feat: layer detection and ambiguity flags"
```

---

### Task 4: Workbook writer

**Files:**
- Create: `splunk_seq/workbook.py`
- Test: `tests/test_workbook.py`

**Interfaces:**
- Consumes: `ApiResult`, `SessionResult`, status/flag constants (Task 3); `OutputCfg` (Task 1)
- Produces:
  - `sheet_name(index: int, total: int, endpoint: str) -> str`
  - `output_path(cfg: OutputCfg, now: datetime) -> Path`
  - `class SequenceWorkbook(path: Path, total: int)` with `add(index: int, result: ApiResult) -> None` (index is 1-based input position) and `save() -> None` (creates parent dir)

- [ ] **Step 1: Write the failing tests**

Assert by `openpyxl.load_workbook(path)` after `save()`.

```python
def test_sheet_name_rules():
    assert sheet_name(1, 5, "/v1/customers/{id}/accounts") == "001_v1_customers_id_accounts"
    assert len(sheet_name(1, 5, "/v1/" + "x" * 60)) == 31
    assert sheet_name(12, 1500, "/a") == "0012_a"
    assert sheet_name(3, 5, "/") == "003"                      # Review Focus 5

def test_output_path():
    assert output_path(OutputCfg("output", "api_sequence"), datetime(2026, 10, 17, 14, 23, 1)) == Path("output/api_sequence_20261017_142301.xlsx")

def test_index_sheet_first_with_header_counts_and_hyperlink(tmp_path):
    # add OK result: 2 sessions (2 rows + 1 row), one AMBIGUOUS flag
    ws = wb["Index"]; assert wb.sheetnames[0] == "Index"
    assert [c.value for c in ws[1]] == ["#", "Input API", "Status", "Sessions found", "Rows", "Ambiguous rows", "Error"]
    assert [c.value for c in ws[2]] == [1, "/v1/a", "OK", 2, 3, 1, None]
    assert ws["B2"].hyperlink.location == "'001_v1_a'!A1"

def test_api_sheet_layout(tmp_path):
    ws = wb["001_v1_a"]
    assert ws["A1"].value == "/v1/a" and ws["A2"].hyperlink.location == "'Index'!A1"
    assert [c.value for c in ws[4]] == ["Session ID", "Timestamp", "Gateway API Endpoint", "Flag"]
    # rows 5-6 session s1, row 7 blank, row 8 session s2; Session ID on every data row
    assert ws.freeze_panes == "A5" and ws.auto_filter.ref.startswith("A4")

def test_column_union_appends_new_columns_right(tmp_path): ...  # 2nd session has extra column "X" → header ends [..., "X", "Flag"]
def test_no_session_still_gets_sheet(tmp_path): ...             # status NO_SESSION, sheet exists with A1 set
def test_error_message_in_index(tmp_path): ...
def test_formula_like_values_stay_text(tmp_path):              # Review Focus 2
    # row value "=HYPERLINK(1)" → reloaded cell value "=HYPERLINK(1)", data_type "s"
def test_illegal_control_chars_stripped(tmp_path):             # Review Focus 3
    # value "ab\x01c" → "abc"
def test_save_after_each_add_keeps_earlier_sheets(tmp_path): ...
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_workbook.py -v` — Expected: FAIL (module missing).

- [ ] **Step 3: Implement `splunk_seq/workbook.py`**

Prefix width `max(3, len(str(total)))`; cleaned = `re.sub(r"[^A-Za-z0-9]+", "_", endpoint).strip("_")`; join with `_` only when cleaned is non-empty; truncate to 31. Write every data cell through one helper that removes `openpyxl.cell.cell.ILLEGAL_CHARACTERS_RE` matches and then sets `cell.data_type = "s"` for strings. Internal hyperlinks via `cell.hyperlink = Hyperlink(ref=..., location=...)` (or `cell.hyperlink = "#'Sheet'!A1"` if the test passes with it). Autofilter ref spans header row to last written row.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_workbook.py -v` — Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add splunk_seq/workbook.py tests/test_workbook.py
git commit -m "feat: indexed workbook writer"
```

---

### Task 5: Proxy fetcher

**Files:**
- Create: `splunk_seq/errors.py`, `splunk_seq/fetch_proxy.py`
- Test: `tests/test_fetch_proxy.py`

**Interfaces:**
- Consumes: `Config` (Task 1), `Row` (Task 3)
- Produces:
  - `errors.py`: `class SearchError(Exception)`, `class LoginExpired(SearchError)`, `class ProxyUnavailable(SearchError)`
  - `parse_export(text: str) -> list[Row]`
  - `build_export_request(cfg: Config, query: str, earliest: str, latest: str, cookies: list[dict]) -> tuple[str, dict[str, str], dict[str, str]]` → (url, form, headers)
  - `PostFn = Callable[[str, dict[str, str], dict[str, str], float], tuple[int, str, str]]` — (url, form, headers, timeout_s) → (status, content_type, body)
  - `class ProxyFetcher(cfg: Config, post: PostFn, cookies: Callable[[], list[dict]])` with `run_search(query: str, earliest: str, latest: str) -> list[Row]`

- [ ] **Step 1: Write the failing tests**

```python
def test_parse_export_keeps_final_results_only():
    text = '\n'.join([
        '{"preview":true,"result":{"a":"x"}}',
        '{"preview":false,"offset":0,"result":{"a":"1","mv":["p","q"]}}',
        'not json',
        '{"preview":false,"lastrow":true}',
    ])
    assert parse_export(text) == [{"a": "1", "mv": "p, q"}]

def test_parse_export_raises_on_fatal_message():
    with pytest.raises(SearchError, match="Unknown search command"):
        parse_export('{"messages":[{"type":"FATAL","text":"Unknown search command \'foo\'"}]}')

def test_build_request(cfg):
    url, form, headers = build_export_request(cfg, "search x", "-1h", "now",
        [{"name": "splunkweb_csrf_token_8000", "value": "tok"}])
    assert url == "https://splunk.local:8000/en-US/splunkd/__raw/services/search/jobs/export"
    assert form == {"search": "search x", "earliest_time": "-1h", "latest_time": "now", "output_mode": "json"}
    assert headers == {"X-Requested-With": "XMLHttpRequest", "X-Splunk-Form-Key": "tok"}

def test_build_request_without_csrf_cookie_omits_header(cfg): ...
@pytest.mark.parametrize("status,ctype,exc", [(401, "application/json", LoginExpired), (302, "text/html", LoginExpired),
    (200, "text/html; charset=utf-8", LoginExpired), (403, "text/html", ProxyUnavailable),
    (404, "text/html", ProxyUnavailable), (500, "application/json", SearchError)])
def test_run_search_maps_responses(cfg, status, ctype, exc): ...   # fake post returns (status, ctype, "")
def test_run_search_passes_timeout_and_returns_rows(cfg): ...      # fake post records timeout == 300; 200 json body → rows
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_fetch_proxy.py -v` — Expected: FAIL (modules missing).

- [ ] **Step 3: Implement `errors.py` and `fetch_proxy.py`**

CSRF cookie = first cookie whose name starts with `splunkweb_csrf_token_`. Status mapping order: 401 or any 3xx (redirect to the login page) → `LoginExpired`; 403/404 → `ProxyUnavailable`; other non-200 → `SearchError(f"HTTP {status}")`; 200 with `text/html` → `LoginExpired`; else `parse_export(body)`. Message types `ERROR`/`FATAL` raise `SearchError` with the joined texts.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_fetch_proxy.py -v` — Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add splunk_seq/errors.py splunk_seq/fetch_proxy.py tests/test_fetch_proxy.py
git commit -m "feat: splunkd web proxy export fetcher"
```

---

### Task 6: Fetch strategy and run orchestration

**Files:**
- Create: `splunk_seq/fetch.py`, `splunk_seq/runner.py`
- Test: `tests/test_fetch.py`, `tests/test_runner.py`

**Interfaces:**
- Consumes: `SearchFn`, `ApiResult`, `SessionResult`, constants (Task 3); `compute_flags` (Task 3); `render_session_query`, `render_sequence_query` (Task 2); `SequenceWorkbook` (Task 4); errors (Task 5); `Config` (Task 1)
- Produces:
  - `with_relogin(search: SearchFn, relogin: Callable[[], bool], log: Callable[[str], None]) -> SearchFn`
  - `class AutoFetcher(proxy: SearchFn, ui: SearchFn, log: Callable[[str], None])` with `run_search(query, earliest, latest) -> list[Row]`
  - `class UiFetcher(page)` with `run_search(...)` raising `SearchError("UI fallback not implemented yet")` (real body in Task 8)
  - `run(apis: list[str], cfg: Config, search: SearchFn, workbook: SequenceWorkbook, log: Callable[[str], None] = print) -> dict[str, int]` — tally keyed by `OK`, `NO_SESSION`, `ERROR`

- [ ] **Step 1: Write the failing tests**

```python
# test_fetch.py
def test_relogin_retries_once_after_successful_login(): ...
    # search raises LoginExpired then returns rows; relogin returns True → rows; log contains
    # "Splunk login expired — log in again in the browser window"
def test_relogin_second_expiry_becomes_search_error(): ...    # raises SearchError, not LoginExpired
def test_relogin_failed_login_becomes_search_error(): ...     # relogin returns False
def test_auto_switches_to_ui_only_on_first_call(): ...
    # proxy raises ProxyUnavailable on call 1 → ui used for call 1 and 2; warning logged once
def test_auto_does_not_switch_after_first_proxy_success(): ...  # call 1 ok, call 2 ProxyUnavailable → raised

# test_runner.py  — fake search dispatches on "dedup" in query (session vs sequence)
def test_ok_api_written_with_flags_and_saved(): ...
def test_no_session_status(): ...
def test_session_rows_without_id_field_is_error(): ...        # Review Focus 4: message contains "sessionId"
def test_error_keeps_completed_sessions_and_continues(): ...  # 2nd sequence query raises → ERROR, 1 session written, next API still OK
def test_workbook_saved_after_every_api(): ...                # spy on save: called len(apis) times
def test_tally(): ...                                         # {"OK": 1, "NO_SESSION": 1, "ERROR": 1}
def test_uses_config_time_range(): ...                        # fake search records (earliest, latest) == cfg.search values
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_fetch.py tests/test_runner.py -v` — Expected: FAIL (modules missing).

- [ ] **Step 3: Implement `fetch.py` and `runner.py`**

`run` follows spec §6 step 5. Session IDs = non-empty `row[session_id_field]` values in order; if rows exist but none have the field → `SearchError(f"Session Query results have no '{field}' field")`. Any exception for an API → `ERROR` with `str(exc)`, keeping sessions already completed. Call `workbook.add(i, result)` then `workbook.save()` for every API (1-based `i`). Log one line per API and per Session.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_fetch.py tests/test_runner.py -v` — Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add splunk_seq/fetch.py splunk_seq/runner.py tests/test_fetch.py tests/test_runner.py
git commit -m "feat: fetch strategy and run orchestration"
```

---

### Task 7: Browser session, CLI, README

**Files:**
- Create: `splunk_seq/browser.py`, `splunk_seq/cli.py`, `splunk_seq/__main__.py`, `README.md`
- Test: `tests/test_browser.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: everything above
- Produces:
  - `wait_until(check: Callable[[], bool], timeout_s: float, interval_s: float = 2.0, sleep=time.sleep, clock=time.monotonic) -> bool`
  - `class BrowserSession(cfg: Config)` — context manager; `wait_for_login() -> bool`; `post: PostFn`; `cookies() -> list[dict]`; `page` attribute
  - `load_input_apis(text: str) -> tuple[list[str], list[str]]` → (apis, duplicates)
  - `build_parser() -> argparse.ArgumentParser`; `main(argv: list[str] | None = None) -> int`

- [ ] **Step 1: Write the failing tests**

```python
# test_browser.py — fake clock/sleep
def test_wait_until_true_when_check_passes(): ...
def test_wait_until_false_after_timeout(): ...   # check never passes; returns False; sleeps at interval_s

# test_cli.py
def test_load_input_apis_skips_comments_blanks_and_dedupes():
    assert load_input_apis(" /a \n\n# c\n  # c2\n/b\n/a\n") == (["/a", "/b"], ["/a"])
def test_main_strips_utf8_bom(tmp_path, monkeypatch): ...     # Review Focus 1: file bytes b"\xef\xbb\xbf/a\n"; read with
                                                              # encoding="utf-8-sig"; captured apis == ["/a"] (monkeypatch BrowserSession + run)
def test_api_and_file_mutually_exclusive(): ...               # main(["run","--api","/a","--file","x"]) == 1
def test_missing_config_returns_1(tmp_path): ...
def test_missing_input_file_returns_1(tmp_path): ...
def test_login_timeout_returns_2(tmp_path, monkeypatch): ...  # fake BrowserSession.wait_for_login → False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_browser.py tests/test_cli.py -v` — Expected: FAIL (modules missing).

- [ ] **Step 3: Implement `browser.py`**

`sync_playwright().start()`, `chromium.launch(channel=cfg.browser.channel, headless=cfg.browser.headless)`, new context and page, `page.goto(cfg.splunk.url)`. `wait_for_login` prints the login prompt, then `wait_until` on `context.request.get(f"{url}/{locale}/splunkd/__raw/services/authentication/current-context?output_mode=json").status == 200` with `login_timeout_seconds`. `post` wraps `context.request.post(url, form=form, headers=headers, timeout=timeout_s * 1000, max_redirects=0)` → `(resp.status, resp.headers.get("content-type", ""), resp.text())`. `cookies()` returns `context.cookies()`. `__exit__` closes browser and stops playwright.

- [ ] **Step 4: Implement `cli.py` and `__main__.py`**

Subcommand `run` with mutually exclusive required `--api`/`--file`, `--config` (default `config.yaml`), `--earliest`, `--latest`. Wrap `parse_args` to turn non-zero `SystemExit` into return `1`. Flow: load config (`ConfigError` → print, 1) → load input (`--file` read with `encoding="utf-8-sig"`; missing → 1; warn on duplicates) → `with_overrides` → `BrowserSession` → `wait_for_login` false → 2 → build search per `fetch_mode` (`proxy`: `ProxyFetcher`; `ui`: `UiFetcher`; `auto`: `AutoFetcher(proxy, ui)`), wrapped in `with_relogin(search, session.wait_for_login, print)` → `SequenceWorkbook(output_path(cfg.output, datetime.now()), len(apis))` → `run` → print path and `OK=… NO_SESSION=… ERROR=…` → 0.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q` — Expected: all PASS.

- [ ] **Step 6: Write `README.md`**

Cover exactly spec §12: setup (`pip install -r requirements.txt`, Edge installed, no `playwright install`), `copy config.example.yaml config.yaml`, usage examples for `--api` / `--file` / `--earliest`, query requirements (Session Query newest first; Sequence Query sorted by `_time`, millisecond `Timestamp`, the four layer columns), the meaning of each Flag and Status, the midnight-crossing limitation, and this manual checklist:
- [ ] Login with SSO is detected and the run starts.
- [ ] Proxy export returns rows (CSRF header accepted).
- [ ] A 2–3 API list yields a workbook with working Index hyperlinks.
- [ ] Expiring the login mid-run triggers the re-login prompt and the run continues.

- [ ] **Step 7: Commit**

```bash
git add splunk_seq/browser.py splunk_seq/cli.py splunk_seq/__main__.py tests/test_browser.py tests/test_cli.py README.md
git commit -m "feat: browser login, CLI entry point, README"
```

---

### Task 8: UI-scrape fallback (do inside the target network)

Only needed if the README checklist shows the proxy is blocked. It cannot be built or verified offline (spec §7).

**Files:**
- Modify: `splunk_seq/fetch.py` (`UiFetcher.run_search`)

**Interfaces:**
- Consumes: `BrowserSession.page` (Task 7)
- Produces: real `UiFetcher.run_search(query, earliest, latest) -> list[Row]`, same contract as `ProxyFetcher`

- [ ] **Step 1: Inspect the live Search app** in the target Splunk version: results-table selectors, how the job-done state shows, rows-per-page control.
- [ ] **Step 2: Implement** navigating to `{url}/{locale}/app/search/search?q=<urlencoded query>&earliest=<e>&latest=<l>`, waiting for job completion (bounded by `search.timeout_seconds`), and reading header and rows across all pages into `list[Row]`.
- [ ] **Step 3: Verify manually** with `fetch_mode: ui` on a 2-API list; compare the workbook against the same run with `fetch_mode: proxy` where possible.
- [ ] **Step 4: Commit**

```bash
git add splunk_seq/fetch.py
git commit -m "feat: UI-scrape search fallback"
```
