import pytest

from splunk_seq.config import load_config
from splunk_seq.errors import LoginExpired, ProxyUnavailable, SearchError
from splunk_seq.fetch_proxy import ProxyFetcher, build_export_request, parse_export


@pytest.fixture
def cfg(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(
        'splunk: {url: "https://splunk.local:8000"}\n'
        "session: {query: x}\n"
        "sequence: {query: y}\n",
        encoding="utf-8",
    )
    return load_config(p)


def test_parse_export_keeps_final_results_only():
    text = "\n".join([
        '{"preview":true,"result":{"a":"x"}}',
        '{"preview":false,"offset":0,"result":{"a":"1","mv":["p","q"]}}',
        "not json",
        '{"preview":false,"lastrow":true}',
    ])
    assert parse_export(text) == [{"a": "1", "mv": "p, q"}]


def test_parse_export_raises_on_fatal_message():
    with pytest.raises(SearchError, match="Unknown search command"):
        parse_export('{"messages":[{"type":"FATAL","text":"Unknown search command \'foo\'"}]}')


def test_build_request(cfg):
    url, form, headers = build_export_request(
        cfg, "search x", "-1h", "now", [{"name": "splunkweb_csrf_token_8000", "value": "tok"}]
    )
    assert url == "https://splunk.local:8000/en-US/splunkd/__raw/services/search/jobs/export"
    assert form == {"search": "search x", "earliest_time": "-1h", "latest_time": "now", "output_mode": "json"}
    assert headers == {"X-Requested-With": "XMLHttpRequest", "X-Splunk-Form-Key": "tok"}


def test_build_request_without_csrf_cookie_omits_header(cfg):
    _, _, headers = build_export_request(cfg, "search x", "-1h", "now", [{"name": "other", "value": "v"}])
    assert headers == {"X-Requested-With": "XMLHttpRequest"}


@pytest.mark.parametrize(
    "status,ctype,exc",
    [
        (401, "application/json", LoginExpired),
        (302, "text/html", LoginExpired),
        (200, "text/html; charset=utf-8", LoginExpired),
        (403, "text/html", ProxyUnavailable),
        (404, "text/html", ProxyUnavailable),
        (500, "application/json", SearchError),
    ],
)
def test_run_search_maps_responses(cfg, status, ctype, exc):
    fetcher = ProxyFetcher(cfg, lambda url, form, headers, timeout: (status, ctype, ""), lambda: [])
    with pytest.raises(exc):
        fetcher.run_search("search x", "-1h", "now")


def test_non_200_error_includes_splunk_message(cfg):
    body = '{"messages":[{"type":"FATAL","text":"Error in \'search\' command: bad"}]}'
    fetcher = ProxyFetcher(cfg, lambda *a: (400, "application/json", body), lambda: [])
    with pytest.raises(SearchError, match="HTTP 400.*Error in 'search' command: bad"):
        fetcher.run_search("search x", "-1h", "now")


def test_csrf_rejection_is_not_reported_as_login_expiry(cfg):
    fetcher = ProxyFetcher(cfg, lambda *a: (401, "text/html", "<p>CSRF validation failed</p>"), lambda: [])
    with pytest.raises(SearchError, match="CSRF") as info:
        fetcher.run_search("search x", "-1h", "now")
    assert not isinstance(info.value, LoginExpired)


def test_run_search_passes_timeout_and_returns_rows(cfg):
    calls = []

    def post(url, form, headers, timeout):
        calls.append(timeout)
        return 200, "application/json", '{"preview":false,"result":{"a":"1"}}'

    assert ProxyFetcher(cfg, post, lambda: []).run_search("search x", "-1h", "now") == [{"a": "1"}]
    assert calls == [300]
