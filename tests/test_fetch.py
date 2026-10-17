import pytest

from splunk_seq.errors import LoginExpired, SearchError
from splunk_seq.fetch import with_relogin

RELOGIN_MSG = "Splunk login expired — log in again in the browser window"


def scripted(*outcomes):
    """A SearchFn that returns or raises each outcome in turn."""
    calls = []

    def search(query, earliest, latest):
        outcome = outcomes[len(calls)]
        calls.append(query)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    search.calls = calls
    return search


def test_relogin_retries_once_after_successful_login():
    logs = []
    search = with_relogin(scripted(LoginExpired("x"), [{"a": "1"}]), lambda: True, logs.append)
    assert search("q", "e", "l") == [{"a": "1"}]
    assert RELOGIN_MSG in logs


def test_relogin_second_expiry_becomes_search_error():
    search = with_relogin(scripted(LoginExpired("x"), LoginExpired("y")), lambda: True, lambda m: None)
    with pytest.raises(SearchError) as info:
        search("q", "e", "l")
    assert not isinstance(info.value, LoginExpired)


def test_relogin_failed_login_becomes_search_error():
    search = with_relogin(scripted(LoginExpired("x")), lambda: False, lambda m: None)
    with pytest.raises(SearchError) as info:
        search("q", "e", "l")
    assert not isinstance(info.value, LoginExpired)
