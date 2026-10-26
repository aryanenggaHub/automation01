# ui_steps Visible Matches Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read Splunk results from the visible table instead of the first DOM match, and make selector problems diagnosable on the workstation without rebuilding the exe.

**Architecture:** One helper in `UiFetcher` picks the first visible match of a selector and remembers ambiguity warnings; every read goes through it. `selector_report()` grows per-match detail and a scrape preview; `job._probe` also saves the page HTML. A `pause` step opens Playwright's Inspector when run from source.

**Tech Stack:** Python 3.10+, Playwright 1.64 (sync API), PyYAML, pytest.

**Spec:** `docs/superpowers/specs/2026-10-26-ui-steps-visible-matches-design.md`

## Global Constraints

- No new dependencies. Packaged exe must keep working with only `ui_steps.yaml` edits.
- Log/report wording is exact where the tests below pin it.
- After code changes run `graphify update .` (project CLAUDE.md).
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- Invalid selector (Playwright throws on `.all()`): `_visible` returns False and the report says `invalid selector (...)`, no crash. → Task 1 test `test_invalid_selector_is_not_visible`.
- Hidden match has no bounding box (`bounding_box()` returns None): report prints `hidden` without size. → Task 3 test `test_selector_report_lists_every_match`.
- `pause:` given an argument (`pause: "x"`): ConfigError, not silently ignored. → Task 2 test `test_bad_step_is_named` new case.
- Page HTML can't be written (page closed / disk error): probe logs `Could not save page HTML: ...` and still returns its exit code. → Task 3 test `test_probe_survives_html_failure`.
- Ambiguity warning must not repeat on every poll of the wait loop (polls every 0.5s). → Task 1 test `test_multiple_visible_matches_warn_once`.

---

### Task 1: Pick the first visible match everywhere, warn on ambiguity, guard empty tables

**Files:**
- Modify: `splunk_seq/fetch_ui.py` (`_visible`, `_results`, `_page_rows`, `_scrape`, `_next_page`)
- Test: `tests/test_fetch_ui.py`

**Interfaces:**
- Produces: `UiFetcher._pick(selector: str, name: str) -> Locator | None` — first visible match of `selector`, None when blank/invalid/no visible match. `name` is the YAML key (`"results.table"`) used in the warning. `UiFetcher._visible(selector: str, name: str) -> bool` = `_pick(...) is not None`. `UiFetcher._warned: set[str]` holds selectors already warned about.
- Approach: `self.page.locator(selector).all()`, keep those with `is_visible()`. Wrap in try/except → None as today.

- [ ] **Step 1: Extend the fakes, write failing tests**

Fakes: `FakePage(visible=(), texts=None, missing=None, matches=None)`. `matches: dict[str, list[bool]]` gives per-selector match visibility (e.g. `{"table": [False, True]}`); selectors not in `matches` behave as today (one match, visible iff in `visible`). `FakeLocator.all()` returns one `FakeMatch` per entry; `FakeMatch` has `is_visible()`, `inner_text()`, `bounding_box()` (None when hidden, else `{"x": 0, "y": 10*i, "width": 100, "height": 20}`), `locator(sub)` and `evaluate_all(js, cell)` returning `page.rows[(selector, index)]` (default `[]`), and `all_inner_texts()` returning `page.headers[(selector, index)]`. Selector `"bad["` raises `ValueError("Unexpected token")` from `.all()`.

```python
def test_table_is_read_from_first_visible_match():
    page = FakePage(visible={"#done"}, matches={"table": [False, True]},
                    headers={("table", 1): ["sessionId"]}, rows={("table", 1): [["s1"]]})
    assert fetcher(page).run_search("search x", "-1h", "now") == [{"sessionId": "s1"}]

def test_visible_table_without_rows_is_an_error_not_empty_result():
    page = FakePage(visible={"#done"}, matches={"table": [True]}, headers={("table", 0): ["sessionId"]})
    with pytest.raises(SearchError, match=r"results\.table matched a table with no rows .*\[table\]"):
        fetcher(page).run_search("search x", "-1h", "now")

def test_multiple_visible_matches_warn_once():
    logs = []
    page = FakePage(visible={"#done"}, matches={"table": [True, True]},
                    headers={("table", 0): ["a"]}, rows={("table", 0): [["1"]]})
    fetcher(page, log=logs.append).run_search("search x", "-1h", "now")
    assert logs.count("  Warning: results.table: 2 visible matches, used #1  [table]") == 1

def test_invalid_selector_is_not_visible():
    assert fetcher(FakePage())._visible("bad[", "results.done") is False
```

`fetcher()` helper gains `log=lambda m: None`. Exact guard message: `f"results.table matched a table with no rows; fix the selector so it only matches the table that holds the results  [{r.table}]"`.

- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_fetch_ui.py -q` — new tests FAIL, existing ones still PASS (fakes are backward compatible).

- [ ] **Step 3: Implement `_pick` / `_visible`** in `splunk_seq/fetch_ui.py` and route every `.first` through `_pick`: error text, table (resolve once in `_scrape` and pass the locator to `_page_rows(table)`), Next button. Raise the guard in `_scrape` when the first page has no rows. Callers pass the YAML name (`"login_page"`, `"results.done"`, …).

- [ ] **Step 4: Run** the same command — all PASS.

- [ ] **Step 5: Commit** `fix: read the first visible match of each ui_steps selector`

---

### Task 2: `pause` step

**Files:**
- Modify: `splunk_seq/ui_steps.py` (`ACTIONS`, `_step`), `splunk_seq/fetch_ui.py` (`_do`), `ui_steps.yaml` (action list comment)
- Test: `tests/test_ui_steps.py`, `tests/test_fetch_ui.py`

**Interfaces:**
- Produces: `Step("pause")` (no selector, no value). YAML form `- pause:` (value `None`); any other value → `ConfigError(f"{where}: 'pause' takes no value")`.
- Behaviour: not frozen → `self.page.pause()`; frozen (`getattr(sys, "frozen", False)`) → log `"  pause step skipped: run from source to open the Playwright Inspector"`.

- [ ] **Step 1: Failing tests**

```python
# test_ui_steps.py: add {"pause": None} to test_every_action_parses → Step("pause")
# and a parametrize case: ([{"pause": "x"}], r"search\[1\]: 'pause' takes no value")

# test_fetch_ui.py
def test_pause_opens_inspector_from_source(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    page = FakePage(visible={"#none"})
    fetcher(page, steps=with_steps({"pause": None})).run_search("search x", "-1h", "now")
    assert ("pause",) in page.calls

def test_pause_is_skipped_in_the_exe(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    logs, page = [], FakePage(visible={"#none"})
    fetcher(page, steps=with_steps({"pause": None}), log=logs.append).run_search("search x", "-1h", "now")
    assert ("pause",) not in page.calls
    assert "  pause step skipped: run from source to open the Playwright Inspector" in logs
```

`with_steps(*steps)` builds STEPS' raw dict with those `search` steps; `FakePage.pause()` records `("pause",)`.

- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_ui_steps.py tests/test_fetch_ui.py -q` — new tests FAIL.
- [ ] **Step 3: Implement** in `ui_steps.py` and `fetch_ui._do`; document `- pause:` in the `ui_steps.yaml` action comment.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat: pause step opens the Playwright Inspector when run from source`

---

### Task 3: Richer "Test UI steps" report + page HTML

**Files:**
- Modify: `splunk_seq/fetch_ui.py` (`selector_report`), `splunk_seq/job.py` (`_probe`), `README.md` (Test UI steps bullet)
- Test: `tests/test_fetch_ui.py`, `tests/test_job.py`

**Interfaces:**
- Consumes: `_pick`, `_page_rows(table)` from Task 1.
- Produces: `selector_report() -> list[str]` in this exact shape:

```
  results.table: 2 match(es), 1 visible  [table]
    #1 hidden
    #2 visible 100x20 at (0,10)  <- used
  preview: headers: sessionId, Timestamp
  preview: row 1: s1 | 10:00
```
Zero matches: `  login_page: 0 match(es)  [#login]`. Invalid: `  name: invalid selector (<first line>)  [sel]` (unchanged). Preview only when a table is picked: up to 3 rows; if none picked: `  preview: no visible results.table`.

- [ ] **Step 1: Failing tests**

```python
def test_selector_report_lists_every_match():
    page = FakePage(visible={"#done"}, matches={"table": [False, True]},
                    headers={("table", 1): ["sessionId", "Timestamp"]},
                    rows={("table", 1): [["s1", "10:00"], ["s2", "10:01"], ["s3", "x"], ["s4", "y"]]})
    report = fetcher(page).selector_report()
    i = report.index("  results.table: 2 match(es), 1 visible  [table]")
    assert report[i + 1:i + 3] == ["    #1 hidden", "    #2 visible 100x20 at (0,10)  <- used"]
    assert "  login_page: 0 match(es)  [#login]" in report
    assert "  preview: headers: sessionId, Timestamp" in report
    assert "  preview: row 3: s3 | x" in report and not any("row 4" in l for l in report)
```

Update `test_selector_report_counts_matches` to the new shape. In `test_job.py`: `FakeFetcher` gets `content()` returning `"<html>rows</html>"`; extend `test_probe_reports_columns_selectors_and_screenshot`:

```python
html = result.log_path.with_name("ui_test_page.html")
assert html.read_text(encoding="utf-8") == "<html>rows</html>"
assert f"Page HTML (contains search results): {html}" in lines

def test_probe_survives_html_failure(...):  # FakeFetcher.content raises RuntimeError("Target closed")
    assert result.exit_code == 0 and "Could not save page HTML: Target closed" in lines
```

- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_fetch_ui.py tests/test_job.py -q` — FAIL.
- [ ] **Step 3: Implement** `selector_report` (size from `bounding_box()`, ints) and in `_probe` write `fetcher.page.content()` to `log_path.with_name("ui_test_page.html")` after the screenshot, try/except like the screenshot. Update the README "Test UI steps" bullet to mention the per-match list, preview and `ui_test_page.html`.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat: Test UI steps lists every match, previews rows and saves the page HTML`

---

### Task 4: Shipped default + real-browser regression + README debugging section

**Files:**
- Modify: `ui_steps.yaml` (`results.table` + comment), `README.md` (new "Debugging selectors from source" under "Running from source")
- Test: `tests/test_fetch_ui.py` (`FAKE_SEARCH_PAGE`)

- [ ] **Step 1: Reproduce Splunk's clone in the fake page.** In `FAKE_SEARCH_PAGE`, insert before the real table, inside `.search-results-statistics`, a header-only clone `<table class="header-clone"><thead><tr><th></th><th>sessionId</th><th>Timestamp</th></tr></thead></table>` (visible). Add:

```python
def test_old_table_selector_hits_the_header_clone(chrome_page):
    steps = load_ui_steps(ROOT / "ui_steps.yaml")
    steps = dataclasses.replace(steps, results=dataclasses.replace(steps.results, table=".search-results-statistics table"))
    with pytest.raises(SearchError, match="results.table matched a table with no rows"):
        search_fake_splunk(chrome_page, make_cfg(), steps)
```
(`search_fake_splunk` gains optional `steps`.)

- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_fetch_ui.py -q` — `test_shipped_steps_read_every_page_of_the_table` FAILS (shipped selector picks the clone); new test PASSES.
- [ ] **Step 3: Change** `ui_steps.yaml` `table:` to `".search-results-statistics table:visible:has(tbody tr)"` with a comment: Splunk draws a header-only copy of the table; `:visible` skips hidden matches, `:has(tbody tr)` skips tables without rows. Extend the header comment's selector list with `:visible` / `:has(...)`. Add README section: install from source (point at existing commands), add `- pause:` where you want to stop, run `.venv\Scripts\python app.py`, click Test UI steps, the Inspector opens on the live page (Pick locator / try selectors), copy the working selector into `ui_steps.yaml`; open `ui_test_page.html` in Chrome to try selectors offline; remove `pause` before using the exe (it's skipped there anyway).
- [ ] **Step 4: Run** full suite `.venv\Scripts\python -m pytest -q` — all PASS (Chrome tests skip if Chrome missing; say so if they skipped). Then `graphify update .`.
- [ ] **Step 5: Commit** `fix: shipped results.table skips Splunk's header-only table copy`
