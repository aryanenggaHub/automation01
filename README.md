# Splunk API Sequence

Give it one API endpoint, or a list of them, from any Layer (Gateway, Microservice, Downstream API, Downstream MQ). For each one, the tool finds the Sessions that endpoint appears in, pulls every Session's end-to-end call sequence from Splunk Enterprise, and writes everything to an Excel workbook. Calls whose order may be wrong because they ran in parallel are flagged.

Terms used here are defined in [GLOSSARY.md](GLOSSARY.md).

## Setup

You need Python 3.10+ and Microsoft Edge (or Chrome). Playwright drives the browser that is already installed, so you do **not** run `playwright install`.

```
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy config.example.yaml config.yaml
```

Edit `config.yaml`: set `splunk.url` and write your two queries (see below). Each key is described in the file itself.

## Usage

```
.venv\Scripts\python -m splunk_seq run --api /v1/customers/accounts
.venv\Scripts\python -m splunk_seq run --file apis.txt
.venv\Scripts\python -m splunk_seq run --file apis.txt --earliest -4h --latest -1h
```

- `--file`: one endpoint per line. Blank lines and lines starting with `#` are ignored, and duplicates are skipped with a warning.
- `--earliest` / `--latest`: override the config's time range for this run only (any Splunk time string).
- `--config`: use a config file other than `config.yaml`.

A browser window opens at your Splunk URL. Log in there (SSO/MFA works); the tool continues as soon as it detects the login. The workbook is written to `output/api_sequence_<YYYYMMDD_HHMMSS>.xlsx` and saved after every API, so a crash keeps finished work. If you open it in Excel mid-run, saves fail with a warning and are retried; close it to let the run save again.

Exit codes: `0` run completed (some APIs may still be `NO_SESSION`/`ERROR`), `1` bad config, bad arguments or missing input file, `2` login not detected in time.

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

## Fetch modes

`fetch_mode: auto` (default) runs searches through Splunk Web's built-in proxy using your browser login, and gets full results as JSON (see [ADR 0001](docs/adr/0001-browser-login-with-splunkd-web-proxy.md)). If that proxy is blocked, `auto` switches to reading the Search page, but **that UI fallback is not built yet**. It needs your real Splunk to build against (plan Task 8). Until then, a blocked proxy shows up as `ERROR` on every API.

If your login expires mid-run, the tool asks you to log in again in the open browser and retries once.

## Manual verification checklist (inside your network)

- [ ] Login with SSO is detected and the run starts. If it is never detected and the console shows `Login check failed: ... certificate ...`, your Splunk uses an internal CA that the tool's HTTP client (Node, not Edge) doesn't trust. Either set the environment variable `NODE_EXTRA_CA_CERTS` to your CA's `.pem` file (preferred), or set `browser.ignore_https_errors: true`.
- [ ] Proxy export returns rows (CSRF header accepted). If every API is `ERROR` with `HTTP 401`/`403`, this is the part to fix in `splunk_seq/fetch_proxy.py`.
- [ ] A 2–3 API list yields a workbook with working Index hyperlinks.
- [ ] Expiring the login mid-run triggers the re-login prompt and the run continues.

## Development

```
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q
```
