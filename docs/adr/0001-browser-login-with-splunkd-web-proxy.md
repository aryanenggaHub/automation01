---
status: proposed
---

# Browser login, data via the splunkd web proxy

Splunk Enterprise sits inside the organization network behind an interactive (likely SSO/MFA) login, and the splunkd management port (8089) is typically not reachable for regular users. We therefore use Playwright only to open a visible browser and let the user log in by hand, then reuse that browser's authenticated cookies to run searches through Splunk Web's built-in proxy (`/<locale>/splunkd/__raw/services/search/jobs/export?output_mode=json`) and receive full results as JSON. Status is `proposed` until the proxy is confirmed reachable in the target environment.

## Considered Options

- **Scrape the results table in the Search UI**: rejected as the primary path because results are paginated, long cells are truncated, and the DOM changes across Splunk versions. Not built in v1; it becomes the fallback only if the web proxy proves blocked in the target network.
- **Splunk REST API on port 8089 with a token**: rejected because users usually cannot reach 8089 or mint tokens in this environment, and it bypasses the SSO login the user already has.
- **Drive Excel to paste results**: rejected; the workbook is written directly instead, so Excel need not be running.
