# Splunk API Sequence

Give it one API endpoint, or a list of them, from any Layer (Gateway, Microservice, Downstream API, Downstream MQ). For each one, the tool finds the Sessions that endpoint appears in, pulls every Session's end-to-end call sequence from Splunk Enterprise, and writes everything to an Excel workbook. Calls whose order may be wrong because they ran in parallel are flagged.

Terms used here are defined in [GLOSSARY.md](GLOSSARY.md).

## Download and run

No Python or installs needed. You only need Google Chrome (or Microsoft Edge).

1. Open this repository's **Releases** page on GitHub and download `SplunkSequence-vX.Y.Z-windows.zip`.
2. Unzip it into a folder you can write to, such as Documents or Desktop (not Program Files). The app keeps its settings, browser profile and results in that folder.
3. Double-click `SplunkSequence.exe`. If Windows SmartScreen warns about an unrecognised app, choose **More info → Run anyway** (the app isn't code-signed).

If Chrome never opens or never reacts, open `chrome://policy` in Chrome and search for **RemoteDebugging**. If `RemoteDebuggingAllowed` is `false`, your company blocks browser automation in Chrome; switch **Browser** to **Edge** in the app.

## Using the window

- **Input APIs**: paste endpoints, one per line (`#` starts a comment), or use **Load file…** to fill the box from a `.txt` file.
- **Settings**: Browser, Splunk URL, time range (any Splunk time, e.g. `-24h` / `now`), Sessions per API, the two queries (see below) and the output folder. **Advanced** holds field and column names, the ambiguity window, and the certificate options.
- **Save** checks the settings and writes `config.yaml` next to the app. Problems are shown in a dialog, such as a missing Splunk URL.
- **Run** saves first, then opens the browser at your Splunk URL. Log in there (SSO/MFA works); the run starts as soon as the login is detected. The app uses its own browser profile (`browser-profile` folder), so you stay logged in between runs. If your company needs a sign-in extension (for example Microsoft's *Windows Accounts*), install it once in that browser window.
- **Stop** finishes the current Input API and stops. Everything done so far is already saved.
- **Open output folder** shows the results: `api_sequence_<YYYYMMDD_HHMMSS>.xlsx` plus a matching `.log` file with everything the log pane showed. Send me the `.log` when something goes wrong.

The workbook is saved after every API. If you open it in Excel mid-run, saves fail with a warning and are retried; close it to let the run save again. If your login expires mid-run, the app asks you to log in again in the open browser and retries once.

## Company certificate

If the log shows `Login check failed: ... certificate ...`, your company inspects HTTPS traffic with its own root certificate, which the app's HTTP client doesn't trust by default. To fix it:

1. In Chrome, open your Splunk URL, click the padlock (or the "tune" icon) → **Connection is secure** → **Certificate is valid**.
2. On the **Details** tab, select the top certificate in the chain (the root), click **Export…**, and save it as **Base-64 encoded (.pem / .crt)**.
3. In the app, open **Advanced**, set **Company CA certificate (.pem)** to that file, and Save.

Only if that is impossible, tick **Ignore HTTPS errors** instead.

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

Searches run through Splunk Web's built-in proxy using your browser login, and come back as full JSON results (see [ADR 0001](docs/adr/0001-browser-login-with-splunkd-web-proxy.md)). If that proxy is blocked, every API shows `ERROR` with the HTTP status. A fallback that reads the Search page would then be built against your real Splunk (plan Task 8).


## Checklist for the first run on the company laptop

- [ ] `SplunkSequence.exe` starts (SmartScreen "Run anyway" is fine).
- [ ] Chrome opens with the app's own profile, and login is detected; on the second run you are still logged in.
- [ ] If certificate errors appear, the Company CA certificate setting fixes them.
- [ ] Searches return rows (CSRF header accepted). If every API is `ERROR` with `HTTP 401`/`403`, send the `.log` file.
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
- Exit codes: `0` run completed (some APIs may still be `NO_SESSION`/`ERROR`), `1` bad config, bad arguments, missing input file or browser failed to start, `2` login not detected in time.
- `app.py` opens the window.

To build the app yourself: `pip install pyinstaller`, then `powershell -File build.ps1`; the result is `dist\SplunkSequence\`. Pushing a tag like `v1.0.1` makes GitHub Actions build, self-test and publish the zip as a Release.
