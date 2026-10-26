# ui_steps.yaml: visible matches and on-workstation debugging

Agreed in a grilling session on 2026-10-26.

## Problem

`UiFetcher` uses `page.locator(selector).first` for every selector. Splunk 9's Statistics view
renders a second copy of the results table (a fixed header clone) that comes first in the DOM, so
`results.table` reports "2 match(es), not visible" and the reader would scrape the wrong table.
"Test UI steps" only says a count and one visible flag, which doesn't show the cause.

## Decisions

1. **YAML stays declarative** (selectors + steps). No JS extraction, no scripting in YAML.
2. **Visibility:** a selector is visible when *any* of its matches is visible.
3. **Reading:** error text, Next button, table headers and rows come from the **first visible match**.
   Headers and rows always come from the same table.
4. **Empty-table guard:** if the chosen table has no rows on its first page and `no_results` is not
   visible, raise `SearchError` naming `results.table` (silent empty results are wrong answers).
5. **Ambiguity warning:** when a selector has more than one visible match, log once per selector
   per run: `Warning: <name>: 2 visible matches, used #1  [<selector>]`.
6. **`pause` step:** `- pause:` in `search`. Run from source it calls `page.pause()` (Playwright
   Inspector on the live page). In the packaged exe it is skipped with a log line.
7. **Richer "Test UI steps":** per selector, every match with visible/hidden, size and position,
   and which one is used; a preview of the headers and first 3 rows the app would read; the page
   HTML saved as `ui_test_page.html` next to the log (overwritten each test, report says it holds
   result data). YAML is already re-read on every click.
8. **Shipped default:** `results.table: ".search-results-statistics table:visible:has(tbody tr)"`,
   with a comment explaining `:visible` and `:has()`.
9. **README:** "Debugging selectors from source" section: run from source, `pause`, the HTML file.

## Out of scope

JS-in-YAML extraction, a YAML scripting language, a live selector playground.
