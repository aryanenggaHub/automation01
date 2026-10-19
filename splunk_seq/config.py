"""Load and validate config.yaml (spec §5)."""

from __future__ import annotations

import dataclasses
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

from .paths import resolve_in_app

CHANNELS = ("chrome", "msedge")

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
    ignore_https_errors: bool
    ca_cert_file: str


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


def _time(section: dict, key: str, default: str) -> str:
    """A Splunk time; blank would silently mean all time, so it is rejected."""
    value = section.get(key, default)
    if value is None or not str(value).strip():
        raise ConfigError(f"Config key 'search.{key}' must not be empty (blank would search all time)")
    return str(value).strip()


def load_config(path: Path) -> Config:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {path}") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"Config file is not valid YAML: {exc}") from None
    return parse_config(raw)


def parse_config(raw: dict) -> Config:
    if not isinstance(raw, dict):
        raise ConfigError("Config file must be a YAML mapping")

    splunk = _section(raw, "splunk")
    browser = _section(raw, "browser")
    search = _section(raw, "search")
    session = _section(raw, "session")
    sequence = _section(raw, "sequence")
    output = _section(raw, "output")

    if not isinstance(browser.get("ignore_https_errors", False), bool):
        raise ConfigError("Config key 'browser.ignore_https_errors' must be true or false")
    channel = browser.get("channel", "chrome")
    if channel not in CHANNELS:
        raise ConfigError(f"Config key 'browser.channel' must be one of {', '.join(CHANNELS)}")
    ca_cert_file = browser.get("ca_cert_file") or ""
    if not isinstance(ca_cert_file, str) or (ca_cert_file and not resolve_in_app(ca_cert_file).is_file()):
        raise ConfigError(f"Config key 'browser.ca_cert_file': file not found: {ca_cert_file}")

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
            channel=channel,
            ignore_https_errors=browser.get("ignore_https_errors", False),
            ca_cert_file=ca_cert_file,
        ),
        search=SearchCfg(
            earliest=_time(search, "earliest", "-24h"),
            latest=_time(search, "latest", "now"),
            timeout_seconds=_positive_int(search, "search", "timeout_seconds", 300),
        ),
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
    search = dataclasses.replace(cfg.search, earliest=earliest or cfg.search.earliest, latest=latest or cfg.search.latest)
    return dataclasses.replace(cfg, search=search)


def save_config(path: Path, raw: dict) -> Config:
    """Validate raw settings, then write them as YAML. Invalid settings leave the file untouched."""
    cfg = parse_config(raw)
    try:
        Path(path).write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Cannot save config to {path}: {exc.strerror or exc}") from None
    return cfg


def load_raw_or_default(path: Path, example: Path) -> tuple[dict, str | None]:
    """Settings for the form: path's raw mapping (unvalidated), else the example with a blank URL."""
    warning = None
    if Path(path).exists():
        try:
            raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw, None
        except (OSError, yaml.YAMLError):
            pass
        backup = Path(path).with_name(Path(path).name + ".bak")
        try:
            shutil.copyfile(path, backup)
            kept = f"; your file was copied to {backup.name}"
        except OSError:
            kept = ""
        warning = f"{Path(path).name} could not be read; showing default settings instead{kept}"
    raw = yaml.safe_load(Path(example).read_text(encoding="utf-8"))
    raw.setdefault("splunk", {})["url"] = ""
    return raw, warning
