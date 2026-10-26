from pathlib import Path

import pytest

from splunk_seq.config import parse_config
from splunk_seq.errors import LoginExpired, SearchError
from splunk_seq.fetch_ui import UiFetcher
from splunk_seq.ui_steps import load_ui_steps, parse_ui_steps

ROOT = Path(__file__).parent.parent

STEPS = parse_ui_steps({
    "login_page": "#login",
    "search": [
        {"goto": "{url}/{locale}/search?q={query}&earliest={earliest}"},
        {"fill": {"selector": "#q", "value": "{query}"}},
        {"wait_for": "#ready"},
    ],
    "results": {
        "done": "#done", "error": "#err", "no_results": "#none",
        "table": "table", "header": "th", "row": "tr", "cell": "td",
    },
})


def make_cfg(**search):
    return parse_config({
        "splunk": {"url": "https://splunk.test"},
        "search": {"timeout_seconds": 5, **search},
        "session": {"query": "x"},
        "sequence": {"query": "y"},
    })


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeMatch:
    """One element a selector matched; inside it every sub-selector reads that match's headers/rows."""

    def __init__(self, page, selector, index, visible):
        self.page = page
        self.key = (selector, index)
        self.selector = selector
        self.visible = visible

    def is_visible(self):
        return self.visible

    def inner_text(self):
        return self.page.texts.get(self.selector, "")

    def bounding_box(self):
        return {"x": 0, "y": 10 * self.key[1], "width": 100, "height": 20} if self.visible else None

    def locator(self, sub):
        return self

    def all_inner_texts(self):
        return self.page.headers.get(self.key, [])

    def evaluate_all(self, js, cell):
        return self.page.rows.get(self.key, [])


class FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    def all(self):
        if self.selector == "bad[":
            raise ValueError("Unexpected token")
        flags = self.page.matches.get(self.selector, [True] if self.selector in self.page.visible else [])
        return [FakeMatch(self.page, self.selector, i, v) for i, v in enumerate(flags)]

    def count(self):
        return len(self.all())


class FakePage:
    """Records actions; the selectors in `visible` are on screen. A wait_for of `missing` times out.

    `matches` gives a selector several matches, {selector: [visible, ...]}; `headers` and `rows`
    are what a match's table holds, keyed by (selector, match index).
    """

    def __init__(self, visible=(), texts=None, missing=None, matches=None, headers=None, rows=None):
        self.visible = set(visible)
        self.texts = texts or {}
        self.missing = missing
        self.matches = matches or {}
        self.headers = headers or {}
        self.rows = rows or {}
        self.calls = []

    def goto(self, url):
        self.calls.append(("goto", url))

    def fill(self, selector, value):
        self.calls.append(("fill", selector, value))

    def wait_for_selector(self, selector, state, timeout):
        if selector == self.missing:
            raise TimeoutError(f"Timeout {timeout}ms exceeded.\nwaiting for {selector}")
        self.calls.append(("wait_for", selector))

    def locator(self, selector):
        return FakeLocator(self, selector)


def fetcher(page, cfg=None, log=lambda m: None):
    fake = FakeClock()
    return UiFetcher(cfg or make_cfg(), STEPS, page, log, fake.sleep, fake.clock)


def test_steps_get_placeholders_url_encoded_only_in_goto():
    page = FakePage(visible={"#none"})
    assert fetcher(page).run_search('search index=x "a b"', "-1h", "now") == []
    query = 'search index=x "a b" | table *'
    assert page.calls == [
        ("goto", "https://splunk.test/en-US/search?q=search%20index%3Dx%20%22a%20b%22%20%7C%20table%20%2A&earliest=-1h"),
        ("fill", "#q", query),
        ("wait_for", "#ready"),
    ]


def test_login_page_means_login_expired():
    with pytest.raises(LoginExpired):
        fetcher(FakePage(visible={"#login"})).run_search("search x", "-1h", "now")


def test_splunk_error_message_is_reported():
    page = FakePage(visible={"#err", "#done"}, texts={"#err": "Unknown search\n command 'foo'."})
    with pytest.raises(SearchError, match="Unknown search command 'foo'.") as info:
        fetcher(page).run_search("search x", "-1h", "now")
    assert not isinstance(info.value, LoginExpired)


def test_failed_step_is_named():
    with pytest.raises(SearchError, match=r"UI step 3 \(wait_for #ready\) failed: Timeout 5000ms exceeded\.$"):
        fetcher(FakePage(missing="#ready")).run_search("search x", "-1h", "now")


def test_failed_step_on_login_page_is_login_expired():
    with pytest.raises(LoginExpired):
        fetcher(FakePage(visible={"#login"}, missing="#ready")).run_search("search x", "-1h", "now")


def test_search_that_never_finishes_names_done_selector():
    with pytest.raises(SearchError, match=r"did not finish within 5s .*results\.done: #done"):
        fetcher(FakePage()).run_search("search x", "-1h", "now")


def test_table_is_read_from_first_visible_match():
    page = FakePage(visible={"#done"}, matches={"table": [False, True]},
                    headers={("table", 1): ["sessionId"]}, rows={("table", 1): [["s1"]]})
    assert fetcher(page).run_search("search x", "-1h", "now") == [{"sessionId": "s1"}]


def test_visible_table_without_rows_is_an_error_not_empty_result():
    page = FakePage(visible={"#done"}, matches={"table": [True]}, headers={("table", 0): ["sessionId"]})
    with pytest.raises(SearchError, match=r"results\.table matched a table with no rows.*\[table\]"):
        fetcher(page).run_search("search x", "-1h", "now")


def test_multiple_visible_matches_warn_once():
    logs = []
    page = FakePage(visible={"#done"}, matches={"table": [True, True]},
                    headers={("table", 0): ["a"]}, rows={("table", 0): [["1"]]})
    fetcher(page, log=logs.append).run_search("search x", "-1h", "now")
    assert logs.count("  Warning: results.table: 2 visible matches, used #1  [table]") == 1


def test_invalid_selector_is_not_visible():
    assert fetcher(FakePage())._visible("bad[", "results.done") is False


def test_selector_report_counts_matches():
    report = fetcher(FakePage(visible={"#done"})).selector_report()
    assert "  results.done: 1 match(es), visible  [#done]" in report
    assert "  login_page: 0 match(es), not visible  [#login]" in report
    assert not any("results.next" in line for line in report)  # blank selectors are skipped


# ---- real browser against a fake Splunk Search page ----------------------------------

FAKE_SEARCH_PAGE = """<!doctype html><html><body>
<div class="jobstatus"><i id="check"></i></div>
<div class="search-results-statistics">
  <table><thead><tr><th></th><th>sessionId</th><th>Timestamp</th></tr></thead><tbody></tbody></table>
  <div class="pagination"><ul><li class="next"><a href="#">Next &raquo;</a></li></ul></div>
</div>
<script>
const pages = [
  [["1", "s1", "10:00"], ["2", "s2", "10:01"], ["3", "s3", "10:02"]],
  [["4", "s4<br>s4b", "10:03"], ["5", "s5", "10:04"]],
];
let p = 0;
const tbody = document.querySelector("tbody"), next = document.querySelector("li.next");
function render() {
  tbody.innerHTML = pages[p].map(r => "<tr>" + r.map(c => "<td>" + c + "</td>").join("") + "</tr>").join("");
  if (p === pages.length - 1) next.classList.add("disabled");
}
next.querySelector("a").onclick = e => {
  e.preventDefault();
  if (!next.classList.contains("disabled")) { p++; setTimeout(render, 100); }
};
setTimeout(() => {  // the job "finishes" after a moment
  render();
  const check = document.getElementById("check");
  check.className = "icon-check";
  check.textContent = "done";
}, 200);
</script></body></html>"""


@pytest.fixture(scope="module")
def chrome_page():
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
    except Exception:
        playwright.stop()
        pytest.skip("Google Chrome is not installed")
    yield browser
    browser.close()
    playwright.stop()


def search_fake_splunk(browser, cfg):
    page = browser.new_page()
    requested = []

    def serve(route):
        requested.append(route.request.url)
        route.fulfill(content_type="text/html", body=FAKE_SEARCH_PAGE)

    page.route("https://splunk.test/**", serve)
    logs = []
    try:
        rows = UiFetcher(cfg, load_ui_steps(ROOT / "ui_steps.yaml"), page, logs.append).run_search("search index=x", "-1h", "now")
    finally:
        page.close()
    return rows, requested, logs


def test_shipped_steps_read_every_page_of_the_table(chrome_page):
    rows, requested, logs = search_fake_splunk(chrome_page, make_cfg())
    assert [r["sessionId"] for r in rows] == ["s1", "s2", "s3", "s4, s4b", "s5"]
    assert rows[0] == {"sessionId": "s1", "Timestamp": "10:00"}  # blank row-number header dropped
    assert "q=search%20index%3Dx%20%7C%20table%20%2A" in requested[0]
    assert logs == []


def test_max_rows_stops_reading_with_a_warning(chrome_page):
    rows, _, logs = search_fake_splunk(chrome_page, make_cfg(max_rows=4))
    assert len(rows) == 4
    assert any("search.max_rows = 4" in line for line in logs)
