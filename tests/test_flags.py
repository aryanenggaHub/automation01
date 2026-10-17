from splunk_seq.config import DEFAULT_LAYER_COLUMNS, SequenceCfg
from splunk_seq.flags import compute_flags
from splunk_seq.models import AMBIGUOUS, BAD_TIMESTAMP, UNKNOWN_LAYER

cfg = SequenceCfg(
    query="q",
    timestamp_field="Timestamp",
    timestamp_format="%H:%M:%S.%f",
    ambiguity_window_ms=500,
    layer_columns=DEFAULT_LAYER_COLUMNS,
)

COLS = {"gw": "Gateway API Endpoint", "ms": "Microservice Endpoint",
        "api": "Downstream Integration (API)", "mq": "Downstream Integration (MQ)"}


def r(ts, **layers):
    row = {"Timestamp": ts} if ts is not None else {}
    for col in COLS.values():
        row[col] = ""
    for short, value in layers.items():
        row[COLS[short]] = value
    return row


def test_same_layer_within_window_both_ambiguous():
    rows = [r("04:21:01.000", ms="A"), r("04:21:01.400", ms="B")]
    assert compute_flags(rows, cfg) == [AMBIGUOUS, AMBIGUOUS]


def test_window_boundary_inclusive():
    assert compute_flags([r("04:21:01.000", ms="A"), r("04:21:01.500", ms="B")], cfg) == [AMBIGUOUS, AMBIGUOUS]
    assert compute_flags([r("04:21:01.000", ms="A"), r("04:21:01.501", ms="B")], cfg) == ["", ""]


def test_different_layers_never_ambiguous():
    assert compute_flags([r("04:21:01.000", gw="A"), r("04:21:01.001", ms="B")], cfg) == ["", ""]


def test_unknown_layer_when_zero_or_two_layers_filled():
    rows = [r("04:21:01.000"), r("04:21:01.000", api="X", mq="Y")]
    assert compute_flags(rows, cfg) == [UNKNOWN_LAYER, UNKNOWN_LAYER]


def test_unknown_layer_beats_bad_timestamp():
    assert compute_flags([r("garbage")], cfg) == [UNKNOWN_LAYER]


def test_bad_timestamp_missing_or_unparseable():
    assert compute_flags([r(None, ms="A"), r("4pm", ms="B")], cfg) == [BAD_TIMESTAMP, BAD_TIMESTAMP]


def test_flagged_rows_excluded_from_comparison():
    rows = [r("04:21:01.000", ms="A"), r("bad", ms="B"), r("04:21:01.600", ms="C")]
    assert compute_flags(rows, cfg) == ["", BAD_TIMESTAMP, ""]


def test_whitespace_only_value_counts_as_empty():
    assert compute_flags([r("04:21:01.000", gw="A", ms="   ")], cfg) == [""]


def test_input_order_preserved_when_unsorted():
    rows = [r("04:21:03.000", ms="C"), r("04:21:01.000", ms="A"), r("04:21:01.200", ms="B")]
    assert compute_flags(rows, cfg) == ["", AMBIGUOUS, AMBIGUOUS]
