from splunk_seq.browser import wait_until


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
