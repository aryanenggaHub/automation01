from pathlib import Path

import pytest

from splunk_seq.config import ConfigError, load_config, with_overrides

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
    assert cfg.browser.channel == "msedge" and cfg.browser.headless is False
    assert (cfg.search.earliest, cfg.search.latest, cfg.search.timeout_seconds) == ("-24h", "now", 300)
    assert cfg.fetch_mode == "auto"
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


def test_invalid_fetch_mode_rejected(tmp_path):
    with pytest.raises(ConfigError, match="fetch_mode"):
        load_config(write(tmp_path, MIN + "fetch_mode: fast\n"))


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
