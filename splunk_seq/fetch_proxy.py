"""Run searches through Splunk Web's splunkd proxy using the browser's login (spec §7, ADR 0001)."""

from __future__ import annotations

import json
from typing import Callable

from .config import Config
from .errors import LoginExpired, ProxyUnavailable, SearchError
from .models import Row

# (url, form, headers, timeout_s) -> (status, content_type, body)
PostFn = Callable[[str, dict[str, str], dict[str, str], float], tuple[int, str, str]]

CSRF_COOKIE_PREFIX = "splunkweb_csrf_token_"


def _cell(value) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return "" if value is None else str(value)


def parse_export(text: str) -> list[Row]:
    rows: list[Row] = []
    for line in text.splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        errors = [m.get("text", "") for m in obj.get("messages") or [] if m.get("type") in ("ERROR", "FATAL")]
        if errors:
            raise SearchError("; ".join(errors))
        if obj.get("preview") is False and isinstance(obj.get("result"), dict):
            rows.append({k: _cell(v) for k, v in obj["result"].items()})
    return rows


def _detail(body: str) -> str:
    """Splunk's own error text from an error response, else the start of the body."""
    try:
        parse_export(body)
    except SearchError as exc:
        return str(exc)
    return " ".join(body.split())[:200] or "empty response"


def build_export_request(
    cfg: Config, query: str, earliest: str, latest: str, cookies: list[dict]
) -> tuple[str, dict[str, str], dict[str, str]]:
    url = f"{cfg.splunk.url}/{cfg.splunk.locale}/splunkd/__raw/services/search/jobs/export"
    form = {"search": query, "earliest_time": earliest, "latest_time": latest, "output_mode": "json"}
    headers = {"X-Requested-With": "XMLHttpRequest"}
    token = next((c["value"] for c in cookies if c.get("name", "").startswith(CSRF_COOKIE_PREFIX)), None)
    if token:
        headers["X-Splunk-Form-Key"] = token
    return url, form, headers


class ProxyFetcher:
    def __init__(self, cfg: Config, post: PostFn, cookies: Callable[[], list[dict]]):
        self.cfg = cfg
        self.post = post
        self.cookies = cookies

    def run_search(self, query: str, earliest: str, latest: str) -> list[Row]:
        url, form, headers = build_export_request(self.cfg, query, earliest, latest, self.cookies())
        status, content_type, body = self.post(url, form, headers, self.cfg.search.timeout_seconds)
        if status == 401 and "csrf" in body.lower():
            raise SearchError(f"HTTP 401: Splunk rejected the CSRF token ({_detail(body)})")
        if status == 401 or 300 <= status < 400:
            raise LoginExpired(f"HTTP {status}")
        if status in (403, 404):
            raise ProxyUnavailable(f"HTTP {status} from splunkd web proxy: {_detail(body)}")
        if status != 200:
            raise SearchError(f"HTTP {status}: {_detail(body)}")
        if "text/html" in content_type.lower():
            raise LoginExpired("Splunk returned a web page instead of results")
        return parse_export(body)
