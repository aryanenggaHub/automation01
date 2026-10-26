# Splunk API Sequence

Give it one API endpoint, or a list of them, from any Layer (Gateway, Microservice, Downstream API, Downstream MQ). For each one, the tool finds the Sessions that endpoint appears in, pulls every Session's end-to-end call sequence from Splunk Enterprise, and writes everything to an Excel workbook. Calls whose order may be wrong because they ran in parallel are flagged.

Terms used here are defined in [GLOSSARY.md](GLOSSARY.md).

## Download and run

No Python or installs needed. You only need Google Chrome (or Microsoft Edge).

1. Open this repository's **Releases** page on GitHub and download `SplunkSequence-vX.Y.Z-windows.zip`.
2. Unzip it into a local folder you can write to that OneDrive does **not** sync, for example `C:\Users\<you>\SplunkSequence` (not Program Files). On company laptops Documents and Desktop are often OneDrive-synced, and syncing the app's live browser profile can corrupt it. The app keeps its settings, browser profile and results in that folder.
3. Double-click `SplunkSequence.exe`. If Windows SmartScreen warns about an unrecognised app, choose **More info → Run anyway** (the app isn't code-signed).

If Chrome never opens or never reacts, open `chrome://policy` in Chrome and search for **RemoteDebugging**. If `RemoteDebuggingAllowed` is `false`, your company blocks browser automation in Chrome; set **Browser** to `msedge` (Microsoft Edge) in the app.

## Using the window

- **Input APIs**: paste endpoints, one per line (`#` starts a comment), or use **Load file…** to fill the box from a `.txt` file.
- **Settings**: Browser, Splunk URL, time range (any Splunk time, e.g. `-24h` / `now`), Sessions per API, the two queries (see below) and the output folder. **Advanced** holds field and column names, the ambiguity window, the row limit per query and *Ignore HTTPS errors*.
- **Save** checks the settings and writes `config.yaml` next to the app. Problems are shown in a dialog, such as a missing Splunk URL.
- **Run** saves first, then opens the browser at your Splunk URL. Log in there (SSO/MFA works), then click **Continue (I'm logged in)**; the run starts then. The app uses its own browser profile (`browser-profile` folder), so you stay logged in between runs. If your company needs a sign-in extension (for example Microsoft's *Windows Accounts*), install it once in that browser window.
- **Stop** finishes the current Input API and stops. Everything done so far is already saved.
- **Test UI steps** runs only the first Input API's Session Query and reports, for each `ui_steps.yaml` selector, every element it matched (visible or hidden, size and position) and which one the app uses, then previews the headers and first 3 rows the app would read. It also saves a screenshot (`..._probe.png`) and the page HTML (`ui_test_page.html`, overwritten by each test; it contains the search results) next to the log. `ui_steps.yaml` is read again on every click, so you can edit a selector and test again without restarting. Use it on the first run, and whenever a run fails on a UI step.
- **Open output folder** shows the results: `api_sequence_<YYYYMMDD_HHMMSS>.xlsx` plus a matching `.log` file with everything the log pane showed. Send me the `.log` when something goes wrong.

The workbook is saved after every API. If you open it in Excel mid-run, saves fail with a warning and are retried; close it to let the run save again. If your login expires mid-run (the login page shows), the app asks you to log in again in the open browser, waits for **Continue**, and retries once.

## How searches run (ui_steps.yaml)

Every search runs in the browser's own Splunk Search page, so Chrome's certificates, proxy and login apply; no company certificate setup is needed. `ui_steps.yaml`, next to the app, says which screens and elements to use:

- `search`: steps that run one query. The default opens `…/app/search/search?q=<query>` on the Statistics tab. Actions are `goto`, `click`, `fill`, `press` and `wait_for`, with `{url}`, `{locale}`, `{query}`, `{earliest}` and `{latest}` placeholders.
- `results`: the element that shows the search has finished (`done`), Splunk's error message, the "No results found" message, the results table, its header, row and cell elements, and the Next-page button. Rows are read page by page, up to `search.max_rows` (default 5000) per query.
- `login_page`: an element only shown on the login page, used to notice an expired login.

The defaults are drafted for Splunk Enterprise 9.x and may not match your Splunk. If **Test UI steps** reports a selector with `0 match(es)`, open the screenshot, find the right element (right-click → **Inspect** in Chrome) and change that selector in `ui_steps.yaml`. Queries that don't already end in a `| table ...` command get `| table *` added, so results always show as a table whose headers name the fields.

If Chrome itself shows a certificate error page for Splunk, tick **Ignore HTTPS errors** in **Advanced**.

## Writing the two queries

**Session Query** (`session.query`): `{input_api}` is replaced with the endpoint, escaped for use inside double quotes. It must output a column named by `session.session_id_field` (default `sessionId`), **newest first**. The tool appends `| fillnull ... | dedup <field> | head ...`, so the first `sessions_per_api` distinct Session IDs it returns are the ones analysed. If no result has that field (e.g. a misspelt `session_id_field`), the API is reported as `ERROR` naming the field. Write it to match the endpoint in every Layer's logs.

**Sequence Query** (`sequence.query`): `{session_id}` is replaced with one Session ID. It must:
- sort by time (`| sort 0 _time`); the tool never re-sorts rows,
- output a millisecond timestamp column matching `sequence.timestamp_field` / `timestamp_format`, e.g. `| eval Timestamp=strftime(_time, "%H:%M:%S.%3N")`,
- output one column per Layer, named as in `sequence.layer_columns`.

Every column the query outputs is copied to Excel in the same order.

## The workbook

- **Index** (first sheet): one row per Input API with `#`, the endpoint (click it to jump to its sheet), Status, Sessions found, Rows, Ambiguous rows, and Error.
- **One sheet per Input API**, named `001_<endpoint>` (cut to Excel's 31-character limit). The full endpoint is in A1, A2 links back to Index, and the header is on row 4. Sessions are stacked with a blank row between them, and each row carries its Session ID and a Flag.

| Status | Meaning |
|---|---|
| `OK` | Sessions found and their sequences fetched |
| `NO_SESSION` | The Session Query returned nothing in the time range |
| `ERROR` | Something failed; the Error column says what. Sessions finished before the failure are still written |

| Flag | Meaning |
|---|---|
| `AMBIGUOUS` | Another call in the same Session and same Layer is within `ambiguity_window_ms` (default 500 ms), so the two may have run in parallel and their order can't be trusted |
| `UNKNOWN_LAYER` | None, or more than one, of the Layer columns has a value on this row |
| `BAD_TIMESTAMP` | The timestamp is missing or doesn't match `timestamp_format` |

**Known limitation:** timestamps are time-of-day, so a Session that crosses midnight can be flagged wrongly.

## How results are fetched

Results are read from the Statistics table on Splunk's Search page (see [ADR 0003](docs/adr/0003-ui-scraping-replaces-splunkd-proxy.md)). Long cell values are copied as Splunk shows them, and multivalue cells are joined with `, `.


## Checklist for the first run on the company laptop

- [ ] `SplunkSequence.exe` starts (SmartScreen "Run anyway" is fine).
- [ ] Chrome opens with the app's own profile, and **Continue** starts the run; on the second run you are still logged in.
- [ ] **Test UI steps** reports `UI steps OK` with the expected columns. If not, fix the selectors it reports in `ui_steps.yaml`, or send the `.log` and `_probe.png`.
- [ ] A search with more than 100 rows returns all of them (paging works).
- [ ] A 2–3 API list yields a workbook with working Index hyperlinks, plus a `.log` next to it.
- [ ] Stop mid-run ends after the current API.

## Running from source

For development, or if you prefer the command line. Needs Python 3.10+.

```
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
copy config.example.yaml config.yaml
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m splunk_seq run --api /v1/customers/accounts
.venv\Scripts\python -m splunk_seq run --file apis.txt --earliest=-4h --latest=-1h
.venv\Scripts\python app.py
```

- `--file`: one endpoint per line; blank lines and `#` lines are ignored, duplicates skipped with a warning.
- `--earliest` / `--latest`: override the time range for this run only. Use the `=` form (`--earliest=-4h`), because a value starting with `-` would otherwise be read as an option.
- `--config`: use a config file other than `config.yaml`.
- Exit codes: `0` run completed (some APIs may still be `NO_SESSION`/`ERROR`), `1` bad config, bad arguments, missing input file or browser failed to start, `2` login not confirmed in time. The command line asks you to press Enter once you are logged in.
- `app.py` opens the window.

### Debugging selectors from source

When **Test UI steps** isn't enough to find the right selector, run the app from source (commands above) and let Playwright's Inspector show you the live page:

1. In `ui_steps.yaml`, add `- pause:` to `search` where you want to stop, usually as the last step.
2. Run `.venv\Scripts\python app.py`, log in, and click **Test UI steps**.
3. The Inspector opens on the logged-in Splunk page at that step. Use **Pick locator** to click an element and see a selector for it, or type a selector to highlight what it matches. Press **Resume** to continue the run.
4. Copy the selector that works into `ui_steps.yaml` and click **Test UI steps** again; no restart needed.

Without Splunk at hand, open `ui_test_page.html` from a previous test in Chrome and try selectors in DevTools (`document.querySelectorAll("...")`); Playwright-only parts such as `:visible` don't work there. Remove the `pause` step when you're done: run from source, it stops every search of a full **Run** until you press **Resume**. (The packaged app skips `pause` steps.)

To build the app yourself: `pip install pyinstaller`, then `powershell -File build.ps1`; the result is `dist\SplunkSequence\`. Pushing a tag like `v1.0.1` makes GitHub Actions build, self-test and publish the zip as a Release.
