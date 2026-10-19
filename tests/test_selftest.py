from splunk_seq.selftest import run_selftest


def test_selftest_passes_in_dev(tmp_path):
    assert run_selftest(tmp_path) is True
    assert (tmp_path / "selftest.ok").exists()
