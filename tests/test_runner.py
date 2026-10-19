import pytest

from splunk_seq.config import load_config
from splunk_seq.errors import SearchError
from splunk_seq.models import AMBIGUOUS, ERROR, NO_SESSION, OK
from splunk_seq.runner import run


@pytest.fixture
def cfg(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(
        'splunk: {url: "https://splunk.local:8000"}\n'
        "session: {query: 'api=\"{input_api}\"'}\n"
        "sequence: {query: 'sid=\"{session_id}\"'}\n"
        "search: {earliest: '-2h', latest: '-1h'}\n",
        encoding="utf-8",
    )
    return load_config(p)


def ms(ts, name):
    return {"Timestamp": ts, "Microservice Endpoint": name}


class FakeSearch:
    """Session queries contain 'dedup'; answers are keyed by the quoted value in the query."""

    def __init__(self, sessions, sequences):
        self.sessions = sessions
        self.sequences = sequences
        self.ranges = []

    def __call__(self, query, earliest, latest):
        self.ranges.append((earliest, latest))
        key = query.split('"')[1]
        table = self.sessions if "dedup" in query else self.sequences
        answer = table[key]
        if isinstance(answer, Exception):
            raise answer
        return answer


class FakeWorkbook:
    def __init__(self):
        self.added = []
        self.saves = 0

    def add(self, index, result):
        self.added.append((index, result))

    def save(self):
        self.saves += 1


def test_ok_api_written_with_flags_and_saved(cfg):
    search = FakeSearch({"/a": [{"sessionId": "s1"}]}, {"s1": [ms("01:00:00.000", "A"), ms("01:00:00.100", "B")]})
    wb = FakeWorkbook()
    run(["/a"], cfg, search, wb, log=lambda m: None)
    index, result = wb.added[0]
    assert index == 1 and result.status == OK
    assert result.sessions[0].session_id == "s1"
    assert result.sessions[0].flags == [AMBIGUOUS, AMBIGUOUS]
    assert wb.saves == 1


def test_no_session_status(cfg):
    wb = FakeWorkbook()
    run(["/a"], cfg, FakeSearch({"/a": []}, {}), wb, log=lambda m: None)
    assert wb.added[0][1].status == NO_SESSION


def test_session_rows_without_id_field_is_error(cfg):
    wb = FakeWorkbook()
    run(["/a"], cfg, FakeSearch({"/a": [{"session_id": "s1"}]}, {}), wb, log=lambda m: None)
    result = wb.added[0][1]
    assert result.status == ERROR and "sessionId" in result.error


def test_missing_id_placeholder_ignored_and_ids_trimmed_to_limit(cfg):
    rows = [{"sessionId": "__NO_SESSION_ID__"}] + [{"sessionId": f"s{i}"} for i in range(11)]
    search = FakeSearch({"/a": rows}, {f"s{i}": [] for i in range(11)})
    wb = FakeWorkbook()
    run(["/a"], cfg, search, wb, log=lambda m: None)
    assert [s.session_id for s in wb.added[0][1].sessions] == [f"s{i}" for i in range(10)]


def test_only_missing_id_placeholder_is_error_naming_field(cfg):
    wb = FakeWorkbook()
    run(["/a"], cfg, FakeSearch({"/a": [{"sessionId": "__NO_SESSION_ID__"}]}, {}), wb, log=lambda m: None)
    result = wb.added[0][1]
    assert result.status == ERROR and "sessionId" in result.error


def test_save_failure_warns_and_run_continues(cfg):
    class LockedOnce(FakeWorkbook):
        def save(self):
            self.saves += 1
            if self.saves == 1:
                raise PermissionError("locked")

    wb, logs = LockedOnce(), []
    tally = run(["/a", "/b"], cfg, FakeSearch({"/a": [], "/b": []}, {}), wb, log=logs.append)
    assert tally["NO_SESSION"] == 2 and wb.saves == 2
    assert any("could not save" in m for m in logs)


def test_failed_final_save_is_retried_at_end(cfg):
    class LockedTwice(FakeWorkbook):
        def save(self):
            self.saves += 1
            if self.saves == 1:
                raise PermissionError("locked")

    wb = LockedTwice()
    run(["/a"], cfg, FakeSearch({"/a": []}, {}), wb, log=lambda m: None)
    assert wb.saves == 2


def test_error_keeps_completed_sessions_and_continues(cfg):
    search = FakeSearch(
        {"/a": [{"sessionId": "s1"}, {"sessionId": "s2"}], "/b": [{"sessionId": "s3"}]},
        {"s1": [ms("01:00:00.000", "A")], "s2": SearchError("HTTP 500"), "s3": [ms("02:00:00.000", "C")]},
    )
    wb = FakeWorkbook()
    run(["/a", "/b"], cfg, search, wb, log=lambda m: None)
    first, second = wb.added[0][1], wb.added[1][1]
    assert first.status == ERROR and first.error == "HTTP 500"
    assert [s.session_id for s in first.sessions] == ["s1"]
    assert second.status == OK


def test_workbook_saved_after_every_api(cfg):
    wb = FakeWorkbook()
    run(["/a", "/b", "/c"], cfg, FakeSearch({"/a": [], "/b": [], "/c": []}, {}), wb, log=lambda m: None)
    assert wb.saves == 3 and [i for i, _ in wb.added] == [1, 2, 3]


def test_tally(cfg):
    search = FakeSearch(
        {"/ok": [{"sessionId": "s1"}], "/none": [], "/bad": SearchError("boom")},
        {"s1": [ms("01:00:00.000", "A")]},
    )
    tally = run(["/ok", "/none", "/bad"], cfg, search, FakeWorkbook(), log=lambda m: None)
    assert tally == {"OK": 1, "NO_SESSION": 1, "ERROR": 1}


def test_uses_config_time_range(cfg):
    search = FakeSearch({"/a": [{"sessionId": "s1"}]}, {"s1": []})
    run(["/a"], cfg, search, FakeWorkbook(), log=lambda m: None)
    assert search.ranges == [("-2h", "-1h"), ("-2h", "-1h")]


def test_should_stop_before_next_api(cfg):
    calls = iter([False, True])
    logs, wb = [], FakeWorkbook()
    tally = run(["/a", "/b", "/c"], cfg, FakeSearch({"/a": [], "/b": [], "/c": []}, {}), wb,
                log=logs.append, should_stop=lambda: next(calls))
    assert [i for i, _ in wb.added] == [1]
    assert "Stopped by user after 1 of 3 APIs" in logs
    assert tally == {"OK": 0, "NO_SESSION": 1, "ERROR": 0}


@pytest.mark.parametrize("bad", ["x | delete", "a b", "[| rest /services]", 'q"', "line\nbreak", "back\slash"])
def test_unsafe_session_ids_skipped(cfg, bad):
    logs, wb = [], FakeWorkbook()
    search = FakeSearch({"/a": [{"sessionId": bad}, {"sessionId": "s1"}]}, {"s1": []})
    run(["/a"], cfg, search, wb, log=logs.append)
    assert [s.session_id for s in wb.added[0][1].sessions] == ["s1"]
    assert any("Skipped unsafe Session ID" in m for m in logs)


def test_only_unsafe_session_ids_is_error(cfg):
    wb = FakeWorkbook()
    run(["/a"], cfg, FakeSearch({"/a": [{"sessionId": "x | delete"}]}, {}), wb, log=lambda m: None)
    result = wb.added[0][1]
    assert result.status == ERROR and "unsafe" in result.error
