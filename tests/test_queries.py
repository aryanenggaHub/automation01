from splunk_seq.config import DEFAULT_LAYER_COLUMNS, SequenceCfg, SessionCfg
from splunk_seq.queries import escape_spl, render_sequence_query, render_session_query


def session_cfg(query):
    return SessionCfg(query=query, session_id_field="sessionId", sessions_per_api=10)


def sequence_cfg(query):
    return SequenceCfg(
        query=query,
        timestamp_field="Timestamp",
        timestamp_format="%H:%M:%S.%f",
        ambiguity_window_ms=500,
        layer_columns=DEFAULT_LAYER_COLUMNS,
    )


def test_escape_backslash_then_quote():
    assert escape_spl('a\\b"c') == 'a\\\\b\\"c'


def test_session_query_substitutes_appends_and_prefixes():
    cfg = session_cfg('index=gw "{input_api}" | table _time sessionId')
    assert (
        render_session_query(cfg, "/v1/a")
        == 'search index=gw "/v1/a" | table _time sessionId | dedup sessionId | head 10'
    )


def test_leading_pipe_or_search_not_prefixed():
    assert render_sequence_query(sequence_cfg("  | tstats count where s={session_id}\n"), "1") == "| tstats count where s=1"
    assert render_sequence_query(sequence_cfg("search index=x s={session_id}"), "1") == "search index=x s=1"


def test_other_braces_untouched():
    q = render_sequence_query(sequence_cfg(r'index=x s="{session_id}" | rex "(?<f>\d{3})"'), "abc")
    assert q == r'search index=x s="abc" | rex "(?<f>\d{3})"'


def test_input_value_is_escaped():
    assert render_session_query(session_cfg('"{input_api}"'), 'a"b').startswith('search "a\\"b"')
