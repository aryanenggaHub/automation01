from pathlib import Path

import yaml

from splunk_seq.form import FIELDS, form_to_raw, raw_to_form

RAW = yaml.safe_load(Path("config.example.yaml").read_text(encoding="utf-8"))


def lookup(raw, key):
    for part in key.split("."):
        raw = raw[part]
    return raw


def test_round_trip_example_config():
    assert form_to_raw(raw_to_form(RAW), RAW) == RAW


def test_int_fields_converted_or_left_for_validation():
    values = {**raw_to_form(RAW), "session.sessions_per_api": " 5 ", "sequence.ambiguity_window_ms": "abc"}
    out = form_to_raw(values, RAW)
    assert out["session"]["sessions_per_api"] == 5
    assert out["sequence"]["ambiguity_window_ms"] == "abc"


def test_form_to_raw_does_not_mutate_base():
    values = {**raw_to_form(RAW), "splunk.url": "https://changed"}
    form_to_raw(values, RAW)
    assert RAW["splunk"]["url"] != "https://changed"


def test_missing_sections_created():
    out = form_to_raw(raw_to_form(RAW), {})
    assert out["sequence"]["layer_columns"]["Downstream MQ"] == "Downstream Integration (MQ)"
    assert out["browser"]["ignore_https_errors"] is False


def test_every_field_key_present_in_example():
    for field in FIELDS:
        lookup(RAW, field.key)


def test_main_and_advanced_split():
    main = [f.label for f in FIELDS if not f.advanced]
    assert main == ["Browser", "Splunk URL", "Earliest", "Latest", "Sessions per API",
                    "Session Query", "Sequence Query", "Output folder"]
