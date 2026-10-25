---
status: accepted
---

# Searches run in the Search page, driven by ui_steps.yaml

Supersedes [ADR 0001](0001-browser-login-with-splunkd-web-proxy.md). On the company laptop the splunkd web proxy calls never worked: they went through Playwright's Node.js HTTP client (`context.request`), which doesn't trust the company's TLS-inspection root certificate or use the system proxy, so the login check failed with `unable to verify the first certificate` and every search would have failed the same way. Chrome itself loads Splunk fine. We therefore drop the HTTP client entirely: the user logs in by hand and confirms with a **Continue** button (Enter on the command line), and each search opens Splunk's Search page, waits for the job to finish and reads the Statistics table page by page. The screens and elements involved live in `ui_steps.yaml` next to the exe, a small fixed set of actions (`goto`, `click`, `fill`, `press`, `wait_for`) plus selectors for the results table. Selectors can then be fixed on site without a rebuild, and **Test UI steps** reports which ones match.

## Considered Options

- **Keep the proxy and give Node the company CA (`NODE_EXTRA_CA_CERTS`)**: this was the shipped approach. It needs every user to export a root certificate, and it still ignores the system proxy.
- **Run the proxy calls as `fetch()` inside the page**: this would use Chrome's network stack and keep JSON results. We decided against it in favour of driving the UI, which needs no Splunk-internal endpoint and matches what users do by hand.
- **Detect the login automatically**: dropped. It needed an API call (the same failing channel), and the user prefers to say when they are logged in.
- **Use the UI's Export download instead of reading the table**: we decided against it in favour of reading the table, because table selectors can be adjusted in `ui_steps.yaml`.

## Consequences

- Selectors depend on the Splunk version; the defaults are drafted for 9.x and must be verified on the real system.
- Queries get `| table *` appended unless they already end in a table command, so results always show as a Statistics table whose headers name the fields.
- `search.max_rows` (default 5000) caps how many rows are read for one query.
- `browser.ca_cert_file` is retired: it is ignored with a warning, and saving from the app removes it.
