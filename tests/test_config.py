from pathlib import Path

import pytest
import yaml

from splunk_seq.config import ConfigError, load_config, load_raw_or_default, parse_config, save_config, with_overrides

MIN = """
splunk: {url: "https://splunk.local:8000/"}
session: {query: 'x "{input_api}"'}
sequence: {query: 'y "{session_id}"'}
"""


def write(tmp_path, text):
    p = tmp_path / "config.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_minimal_config_gets_spec_defaults(tmp_path):
    cfg = load_config(write(tmp_path, MIN))
    assert cfg.splunk.url == "https://splunk.local:8000"
    assert cfg.splunk.locale == "en-US" and cfg.splunk.login_timeout_seconds == 300
    assert cfg.browser.channel == "chrome" and cfg.browser.ignore_https_errors is False
    assert (cfg.search.earliest, cfg.search.latest, cfg.search.timeout_seconds) == ("-24h", "now", 300)
    assert cfg.search.max_rows == 5000 and cfg.warnings == ()
    assert cfg.session.session_id_field == "sessionId" and cfg.session.sessions_per_api == 10
    assert cfg.sequence.timestamp_field == "Timestamp"
    assert cfg.sequence.timestamp_format == "%H:%M:%S.%f"
    assert cfg.sequence.ambiguity_window_ms == 500
    assert cfg.sequence.layer_columns == {
        "Gateway": "Gateway API Endpoint",
        "Microservice": "Microservice Endpoint",
        "Downstream API": "Downstream Integration (API)",
        "Downstream MQ": "Downstream Integration (MQ)",
    }
    assert (cfg.output.dir, cfg.output.filename_prefix) == ("output", "api_sequence")


@pytest.mark.parametrize(
    "key,line",
    [
        ("splunk.url", 'splunk: {url: "https://splunk.local:8000/"}'),
        ("session.query", "session: {query: 'x \"{input_api}\"'}"),
        ("sequence.query", "sequence: {query: 'y \"{session_id}\"'}"),
    ],
)
def test_missing_required_key_is_named(tmp_path, key, line):
    text = MIN.replace(line, "")
    with pytest.raises(ConfigError, match=key.replace(".", r"\.")):
        load_config(write(tmp_path, text))


def test_non_positive_int_rejected(tmp_path):
    text = MIN.replace("session: {query:", "session: {sessions_per_api: 0, query:")
    with pytest.raises(ConfigError, match=r"session\.sessions_per_api"):
        load_config(write(tmp_path, text))


def test_non_mapping_yaml_rejected(tmp_path):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, "- a\n- b\n"))


def test_overrides_replace_only_given_values(tmp_path):
    cfg = with_overrides(load_config(write(tmp_path, MIN)), "-1h", None)
    assert (cfg.search.earliest, cfg.search.latest) == ("-1h", "now")


def test_example_config_is_valid():
    load_config(Path("config.example.yaml"))


def test_parse_config_accepts_dict():
    assert parse_config(yaml.safe_load(MIN)).splunk.url == "https://splunk.local:8000"


def test_invalid_channel_rejected():
    raw = yaml.safe_load(MIN)
    raw["browser"] = {"channel": "firefox"}
    with pytest.raises(ConfigError, match=r"browser\.channel"):
        parse_config(raw)


def test_retired_ca_cert_file_warns_and_save_drops_it(tmp_path):
    raw = yaml.safe_load(MIN)
    raw["browser"] = {"ca_cert_file": "nope.pem"}
    assert "ca_cert_file is no longer used" in parse_config(raw).warnings[0]
    p = tmp_path / "config.yaml"
    save_config(p, raw)
    assert load_config(p).warnings == ()


def test_save_config_round_trip(tmp_path):
    raw = yaml.safe_load(MIN)
    p = tmp_path / "config.yaml"
    save_config(p, raw)
    assert load_config(p) == parse_config(raw)


def test_save_config_invalid_leaves_file_untouched(tmp_path):
    p = write(tmp_path, MIN)
    before = p.read_bytes()
    with pytest.raises(ConfigError):
        save_config(p, {"splunk": {"url": ""}})
    assert p.read_bytes() == before


def test_save_config_unwritable_raises_config_error(tmp_path, monkeypatch):
    def deny(*args, **kwargs):
        raise PermissionError("Access is denied")

    monkeypatch.setattr(Path, "write_text", deny)
    with pytest.raises(ConfigError, match="Cannot save config"):
        save_config(tmp_path / "config.yaml", yaml.safe_load(MIN))


def test_load_raw_or_default_missing_file(tmp_path):
    raw, warning = load_raw_or_default(tmp_path / "config.yaml", Path("config.example.yaml"))
    assert raw["splunk"]["url"] == "" and raw["session"]["sessions_per_api"] == 10
    assert warning is None


def test_load_raw_or_default_invalid_values_kept(tmp_path):
    p = write(tmp_path, MIN.replace("session: {query:", "session: {sessions_per_api: ten, query:"))
    raw, warning = load_raw_or_default(p, Path("config.example.yaml"))
    assert raw["session"]["sessions_per_api"] == "ten" and warning is None


def test_load_raw_or_default_broken_yaml(tmp_path):
    p = write(tmp_path, "a: [")
    raw, warning = load_raw_or_default(p, Path("config.example.yaml"))
    assert raw["splunk"]["url"] == ""
    assert "config.yaml" in warning


def test_broken_config_backed_up_before_defaults_shown(tmp_path):
    p = write(tmp_path, "a: [")
    raw, warning = load_raw_or_default(p, Path("config.example.yaml"))
    assert (tmp_path / "config.yaml.bak").read_text(encoding="utf-8") == "a: ["
    assert "config.yaml.bak" in warning


@pytest.mark.parametrize("key", ["earliest", "latest"])
def test_blank_time_range_rejected(key):
    raw = yaml.safe_load(MIN)
    raw["search"] = {key: "  "}
    with pytest.raises(ConfigError, match=rf"search\.{key}"):
        parse_config(raw)
