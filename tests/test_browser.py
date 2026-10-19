from splunk_seq.browser import ca_cert_env, wait_until
from splunk_seq.config import parse_config

BASE = {"splunk": {"url": "https://s:8000"}, "session": {"query": "x"}, "sequence": {"query": "y"}}


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def test_wait_until_true_when_check_passes():
    fake = FakeClock()
    answers = iter([False, False, True])
    assert wait_until(lambda: next(answers), 10, 2.0, fake.sleep, fake.clock) is True
    assert fake.sleeps == [2.0, 2.0]


def test_wait_until_false_after_timeout():
    fake = FakeClock()
    assert wait_until(lambda: False, 5, 2.0, fake.sleep, fake.clock) is False
    assert fake.sleeps == [2.0, 2.0, 2.0]


def test_wait_until_treats_check_exception_as_not_ready():
    fake = FakeClock()
    answers = iter([OSError("connection reset"), True])

    def check():
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    errors = []
    assert wait_until(check, 10, 2.0, fake.sleep, fake.clock, on_error=errors.append) is True
    assert [str(e) for e in errors] == ["connection reset"]


def test_wait_until_returns_false_when_stopped():
    fake = FakeClock()
    assert wait_until(lambda: False, 100, 2.0, fake.sleep, fake.clock, should_stop=lambda: True) is False
    assert fake.sleeps == []


def test_ca_cert_env_empty_when_unset():
    assert ca_cert_env(parse_config(BASE)) == {}


def test_ca_cert_env_resolves_relative_path_with_spaces(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "certs").mkdir()
    (tmp_path / "certs" / "My Corp CA.pem").write_text("pem", encoding="utf-8")
    cfg = parse_config({**BASE, "browser": {"ca_cert_file": "certs/My Corp CA.pem"}})
    assert ca_cert_env(cfg) == {"NODE_EXTRA_CA_CERTS": str(tmp_path / "certs" / "My Corp CA.pem")}
