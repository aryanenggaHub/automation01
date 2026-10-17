"""Load and validate config.yaml (spec §5)."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path

import yaml

FETCH_MODES = ("auto", "proxy", "ui")

DEFAULT_LAYER_COLUMNS = {
    "Gateway": "Gateway API Endpoint",
    "Microservice": "Microservice Endpoint",
    "Downstream API": "Downstream Integration (API)",
    "Downstream MQ": "Downstream Integration (MQ)",
}


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class SplunkCfg:
    url: str
    locale: str
    login_timeout_seconds: int


@dataclass(frozen=True)
class BrowserCfg:
    channel: str
    headless: bool
    ignore_https_errors: bool


@dataclass(frozen=True)
class SearchCfg:
    earliest: str
    latest: str
    timeout_seconds: int


@dataclass(frozen=True)
class SessionCfg:
    query: str
    session_id_field: str
    sessions_per_api: int


@dataclass(frozen=True)
class SequenceCfg:
    query: str
    timestamp_field: str
    timestamp_format: str
    ambiguity_window_ms: int
    layer_columns: dict[str, str]


@dataclass(frozen=True)
class OutputCfg:
    dir: str
    filename_prefix: str


@dataclass(frozen=True)
class Config:
    splunk: SplunkCfg
    browser: BrowserCfg
    search: SearchCfg
    fetch_mode: str
    session: SessionCfg
    sequence: SequenceCfg
    output: OutputCfg


def _section(raw: dict, name: str) -> dict:
    value = raw.get(name) or {}
    if not isinstance(value, dict):
        raise ConfigError(f"Config key '{name}' must be a mapping")
    return value


def _required_str(section: dict, prefix: str, key: str) -> str:
    value = section.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Missing required config key: {prefix}.{key}")
    return value


def _str(section: dict, prefix: str, key: str, default: str) -> str:
    value = section.get(key, default)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"Config key '{prefix}.{key}' must be a non-empty string")
    return value


def _positive_int(section: dict, prefix: str, key: str, default: int) -> int:
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"Config key '{prefix}.{key}' must be a positive integer")
    return value


def load_config(path: Path) -> Config:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {path}") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"Config file is not valid YAML: {exc}") from None
    if not isinstance(raw, dict):
        raise ConfigError("Config file must be a YAML mapping")

    splunk = _section(raw, "splunk")
    browser = _section(raw, "browser")
    search = _section(raw, "search")
    session = _section(raw, "session")
    sequence = _section(raw, "sequence")
    output = _section(raw, "output")

    fetch_mode = raw.get("fetch_mode", "auto")
    if fetch_mode not in FETCH_MODES:
        raise ConfigError(f"Config key 'fetch_mode' must be one of {', '.join(FETCH_MODES)}")

    for key in ("headless", "ignore_https_errors"):
        if not isinstance(browser.get(key, False), bool):
            raise ConfigError(f"Config key 'browser.{key}' must be true or false")

    layer_columns = sequence.get("layer_columns", DEFAULT_LAYER_COLUMNS)
    if (
        not isinstance(layer_columns, dict)
        or not layer_columns
        or not all(isinstance(k, str) and isinstance(v, str) and v for k, v in layer_columns.items())
    ):
        raise ConfigError("Config key 'sequence.layer_columns' must map Layer names to column names")

    return Config(
        splunk=SplunkCfg(
            url=_required_str(splunk, "splunk", "url").strip().rstrip("/"),
            locale=_str(splunk, "splunk", "locale", "en-US"),
            login_timeout_seconds=_positive_int(splunk, "splunk", "login_timeout_seconds", 300),
        ),
        browser=BrowserCfg(
            channel=_str(browser, "browser", "channel", "msedge"),
            headless=browser.get("headless", False),
            ignore_https_errors=browser.get("ignore_https_errors", False),
        ),
        search=SearchCfg(
            earliest=str(search.get("earliest", "-24h")),
            latest=str(search.get("latest", "now")),
            timeout_seconds=_positive_int(search, "search", "timeout_seconds", 300),
        ),
        fetch_mode=fetch_mode,
        session=SessionCfg(
            query=_required_str(session, "session", "query"),
            session_id_field=_str(session, "session", "session_id_field", "sessionId"),
            sessions_per_api=_positive_int(session, "session", "sessions_per_api", 10),
        ),
        sequence=SequenceCfg(
            query=_required_str(sequence, "sequence", "query"),
            timestamp_field=_str(sequence, "sequence", "timestamp_field", "Timestamp"),
            timestamp_format=_str(sequence, "sequence", "timestamp_format", "%H:%M:%S.%f"),
            ambiguity_window_ms=_positive_int(sequence, "sequence", "ambiguity_window_ms", 500),
            layer_columns=dict(layer_columns),
        ),
        output=OutputCfg(
            dir=_str(output, "output", "dir", "output"),
            filename_prefix=_str(output, "output", "filename_prefix", "api_sequence"),
        ),
    )


def with_overrides(cfg: Config, earliest: str | None, latest: str | None) -> Config:
    search = dataclasses.replace(
        cfg.search,
        earliest=earliest if earliest is not None else cfg.search.earliest,
        latest=latest if latest is not None else cfg.search.latest,
    )
    return dataclasses.replace(cfg, search=search)
