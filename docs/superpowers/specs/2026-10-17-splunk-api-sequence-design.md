# Splunk API Sequence Tool — Design Spec

Status: approved design, not yet built. Vocabulary follows [GLOSSARY.md](../../../GLOSSARY.md); the data-access approach is recorded in [ADR 0001](../../adr/0001-browser-login-with-splunkd-web-proxy.md).

## 1. Purpose

A Python CLI that takes one or more **Input APIs** (an endpoint from any **Layer**), finds the **Sessions** they appear in via a Splunk Enterprise instance on the organization network, rebuilds each Session's **API Sequence** across Gateway → Microservice → Downstream API / Downstream MQ, and writes everything to a new Excel workbook. Calls whose order may be wrong because they ran in parallel are marked **Ambiguous**.

The tool is developed outside the target network and copied in, so **every environment-specific value lives in `config.yaml`**; no Splunk URL, query, or field name is hard-coded.

## 2. Out of scope (v1)

- Resolving parallel calls with span/correlation IDs (only flagging them).
- Splunk Cloud, scheduled runs, CI triggers.
- Driving the Excel application (the `.xlsx` is written directly).
- Downloading Playwright's bundled browsers (the installed Edge/Chrome is used).

## 3. Stack

- Python 3.10+
- `playwright` (browser login and authenticated HTTP via the browser context)
- `openpyxl` (workbook output)
- `pyyaml` (config)
- `pytest` (dev only)

Ship `requirements.txt` (runtime) and `requirements-dev.txt` (adds pytest). Setup must **not** require `playwright install`; the browser is launched with `channel` from config (default `msedge`).

## 4. CLI

```
python -m splunk_seq run (--api <endpoint> | --file <path>) [--config config.yaml] [--earliest <splunk time>] [--latest <splunk time>]
```

- `--api` and `--file` are mutually exclusive; exactly one is required.
- `--file`: UTF-8 text, one endpoint per line. Blank lines and lines whose first non-space character is `#` are ignored. Surrounding whitespace is stripped. Duplicate endpoints are processed once (first occurrence wins) and a warning is printed.
- `--config` defaults to `config.yaml` in the current directory.
- `--earliest` / `--latest` override `search.earliest` / `search.latest` for this run only.
- Exit code `0` if the run completed (even if some APIs ended in `NO_SESSION`/`ERROR`), `1` if the config is invalid or input file is missing, `2` if login never succeeded.
- Progress is printed to the console, one line per Input API and per Session.

## 5. Configuration (`config.yaml`)

Ship a `config.example.yaml` with every key and a comment; the tool reads `config.yaml`. Missing required keys → exit 1 with a message naming the key.

```yaml
splunk:
  url: https://splunk.example.internal:8000   # required, no trailing slash
  locale: en-US
  login_timeout_seconds: 300

browser:
  channel: msedge            # msedge | chrome
  headless: false            # must stay false: the user logs in by hand

search:
  earliest: -24h
  latest: now
  timeout_seconds: 300       # per query

fetch_mode: auto             # auto | proxy | ui   (see §7)

session:
  # {input_api} is replaced with the Input API. Results must come out newest first.
  query: >
    index=gateway OR index=ms OR index=downstream "{input_api}"
    | table _time sessionId
  session_id_field: sessionId
  sessions_per_api: 10

sequence:
  # {session_id} is replaced with one Session ID.
  query: >
    index=gateway OR index=ms OR index=downstream sessionId="{session_id}"
    | sort 0 _time
    | eval Timestamp=strftime(_time, "%H:%M:%S.%3N")
    | table Timestamp "Gateway API Endpoint" "Microservice Endpoint" "Downstream Integration (API)" "Downstream Integration (MQ)"
  timestamp_field: Timestamp
  timestamp_format: "%H:%M:%S.%f"     # Python strptime format of timestamp_field
  ambiguity_window_ms: 500
  layer_columns:
    Gateway: Gateway API Endpoint
    Microservice: Microservice Endpoint
    Downstream API: Downstream Integration (API)
    Downstream MQ: Downstream Integration (MQ)

output:
  dir: output
  filename_prefix: api_sequence
```

### Query templating rules

- Substitute **only** the literal tokens `{input_api}` and `{session_id}` (plain string replace). Do **not** use `str.format`; SPL may legitimately contain other braces.
- Before substitution, escape the value for use inside an SPL double-quoted string: `\` → `\\`, `"` → `\"`.
- If the final query does not start with `search ` or `|` (after stripping), prefix it with `search `.
- The tool appends to the Session Query: ` | fillnull value="__NO_SESSION_ID__" <session_id_field> | dedup <session_id_field> | head <sessions_per_api + 1>`, then ignores the `__NO_SESSION_ID__` value and keeps the first `sessions_per_api` IDs. Dedup keeps the first occurrence, so the query's own order defines "most recent"; the example config's comment must state the newest-first requirement. (Amended after review: a bare `dedup` drops events lacking the field, so a misspelt `session_id_field` would read as `NO_SESSION` instead of an error naming the field.)

## 6. Run flow

1. Load and validate config; apply CLI overrides; load Input APIs.
2. Launch the browser (`channel`, `headful`), open `splunk.url`, and tell the user in the console to log in.
3. **Wait for login**: poll `GET {url}/{locale}/splunkd/__raw/services/authentication/current-context?output_mode=json` through the browser context's request API every 2 s until it returns HTTP 200, or until `login_timeout_seconds` → exit 2.
4. Create the workbook (§8) at `{output.dir}/{filename_prefix}_{YYYYMMDD_HHMMSS}.xlsx` (create the dir if needed).
5. For each Input API, in input order:
   1. Run the Session Query → list of Session IDs (≤ `sessions_per_api`).
   2. If none → status `NO_SESSION`.
   3. For each Session ID, run the Sequence Query → rows; compute Flags (§9).
   4. Write the API's sheet and index row; **save the workbook**.
   5. On any exception for this API: status `ERROR`, error message recorded, any partial rows still written, continue with the next API.
6. Print the output path and a one-line tally (OK / NO_SESSION / ERROR counts).

### Expired login

If a search request returns 401, or is redirected to a login page (HTML instead of JSON), print "Splunk login expired — log in again in the browser window", re-enter the step 3 wait loop, then retry that request **once**. A second failure becomes an `ERROR` for that API.

## 7. Fetching search results

### `proxy` mode (primary)

- `POST {url}/{locale}/splunkd/__raw/services/search/jobs/export` using the **browser context's** request API (shares the login cookies).
- Form fields: `search=<final query>`, `earliest_time`, `latest_time`, `output_mode=json`.
- Headers: `X-Requested-With: XMLHttpRequest`, and `X-Splunk-Form-Key` set to the value of the cookie named `splunkweb_csrf_token_<port>` (Splunk Web's CSRF check). **Verify this against the real instance**; it is the most likely thing to need adjustment.
- The response is newline-delimited JSON objects. Keep objects with `"preview": false` that have a `result` key; each `result` is one row (dict of field → value; multi-value fields arrive as lists and are joined with `, `). Lines that fail to parse, or objects with only `lastrow`/`messages`, are skipped; any `messages` of type `ERROR`/`FATAL` raise an error containing their text.
- Timeout: `search.timeout_seconds`.

### `ui` mode (fallback)

Navigate to the Search app with the query and time range in the URL, wait for the job to finish, and read the results table. Selectors and pagination handling **must be built against the real Splunk version** and cannot be verified offline, so implement this as a separate, later task behind the same interface as proxy mode.

### `auto` mode

Use proxy mode. If the first proxy search of the run fails with HTTP 403/404 (proxy blocked, not a query error), print a warning and switch to ui mode for the rest of the run.

### Interface

Both modes implement one function shape: `run_search(query, earliest, latest) -> list[dict[str, str]]`, rows in the order Splunk returned them. Everything else depends only on this.

## 8. Workbook layout

### Sheet 1: `Index`

Header row, then one row per Input API in input order:

| # | Input API | Status | Sessions found | Rows | Ambiguous rows | Error |
|---|---|---|---|---|---|---|

- `Input API` cell is an internal hyperlink to that API's sheet (`#'<sheet name>'!A1`).
- `Status` ∈ `OK`, `NO_SESSION`, `ERROR`. Sessions found but zero sequence rows is still `OK` with `Rows = 0`.
- `Rows` counts data rows across all Sessions; `Ambiguous rows` counts rows whose Flag is `AMBIGUOUS`.
- An API with `NO_SESSION` still gets a sheet (with the endpoint in A1 and no data), so every hyperlink works.

### Sheets 2…n: one per Input API

- **Name**: `{index:0Nd}_{cleaned}` where N = max(3, digits in the input count), and `cleaned` = endpoint with every run of characters outside `[A-Za-z0-9]` replaced by `_`, leading/trailing `_` stripped; the whole name truncated to 31 characters. The numeric prefix guarantees uniqueness.
- `A1`: the full Input API endpoint. `A2`: hyperlink "← Index" back to `Index!A1`.
- Row 4: header `Session ID | <query columns, in query order> | Flag`.
- Data from row 5. Sessions stacked in the order returned by the Session Query, each Session's rows in query order (the tool never re-sorts), one **blank row** between Sessions. `Session ID` is filled on every data row.
- Column set: columns of the first Session's results in order; columns first seen in later Sessions are appended to the right.
- Freeze panes below the header; enable autofilter on the header row.

## 9. Flags and ambiguity

Computed per Session, per row. The Flag cell holds exactly one value, by precedence:

1. `UNKNOWN_LAYER`: zero or more than one of the configured `layer_columns` is non-empty on the row.
2. `BAD_TIMESTAMP`: `timestamp_field` is missing or does not parse with `timestamp_format`.
3. `AMBIGUOUS`: another row in the **same Session and same Layer** has a timestamp within `ambiguity_window_ms` (inclusive) of this row's.
4. empty.

Rows flagged `UNKNOWN_LAYER` or `BAD_TIMESTAMP` never take part in the ambiguity comparison. Both rows of an ambiguous pair are flagged. Timestamps are time-of-day; if a Session crosses midnight the comparison may be wrong. Accept that limitation in v1 and note it in the README.

## 10. Suggested module layout

```
splunk_seq/
  __main__.py      # python -m splunk_seq
  cli.py           # argparse, input-file parsing
  config.py        # load/validate YAML, defaults, CLI overrides
  queries.py       # templating, escaping, session-query suffix
  browser.py       # launch Edge, wait-for-login, re-login prompt
  fetch_proxy.py   # export endpoint, NDJSON parsing
  fetch_ui.py      # fallback (later task)
  flags.py         # layer detection, ambiguity
  workbook.py      # Index + per-API sheets, naming, hyperlinks, save
  runner.py        # orchestrates §6
tests/
config.example.yaml
requirements.txt
requirements-dev.txt
README.md
```

## 11. Testing

Unit-test everything that does not need a live Splunk or browser (TDD):

- **config**: required-key errors, defaults, CLI overrides.
- **cli**: input-file parsing (comments, blanks, whitespace, duplicates), mutually exclusive args.
- **queries**: token substitution, quote/backslash escaping, `search ` prefixing, session suffix; other braces in SPL left untouched.
- **fetch_proxy**: NDJSON parsing from canned response text (preview rows dropped, multi-value join, `messages` errors, junk lines), request building (form fields, CSRF header from a given cookie jar), 401/HTML detection. Inject the HTTP call so no network is needed.
- **flags**: every precedence case; window boundary (exactly 500 ms = ambiguous, 501 ms = not); different Layers never ambiguous; per-Session isolation.
- **workbook**: sheet-name cleaning/truncation/prefix width, hyperlinks, header positions, blank rows between Sessions, column union, Index counts. Assert by reopening the saved file with openpyxl.
- **runner**: with a fake `run_search`, verify statuses, continue-after-error, save-after-every-API, and the re-login retry path.

**Manual verification** inside the target network (document as a checklist in the README): login detection works with SSO; proxy export returns rows (CSRF header accepted); a 2–3 API list produces a correct workbook; an expired login mid-run triggers the prompt.

## 12. README must cover

Setup without internet browser download (`pip install -r requirements.txt`, Edge installed), copying `config.example.yaml` → `config.yaml`, the requirements on the two queries (Session Query newest first; Sequence Query sorted by time with millisecond timestamp and the layer columns), the meaning of each Flag, and the manual verification checklist.
