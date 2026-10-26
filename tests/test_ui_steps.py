from pathlib import Path

import pytest

from splunk_seq.config import ConfigError
from splunk_seq.ui_steps import Step, load_ui_steps, parse_ui_steps

ROOT = Path(__file__).parent.parent

MIN = {
    "login_page": "#login",
    "search": [{"goto": "{url}/s?q={query}"}],
    "results": {"done": "#done", "table": "table", "header": "th", "row": "tr", "cell": "td"},
}


def test_shipped_ui_steps_is_valid():
    steps = load_ui_steps(ROOT / "ui_steps.yaml")
    assert steps.search[0].action == "goto" and "{query}" in steps.search[0].value


def test_every_action_parses():
    raw = {**MIN, "search": [
        {"goto": "{url}"},
        {"click": "#a"},
        {"fill": {"selector": "#q", "value": "{query}"}},
        {"press": {"selector": "#q", "key": "Enter"}},
        {"wait_for": "#b"},
        {"pause": None},
    ]}
    assert parse_ui_steps(raw).search == (
        Step("goto", value="{url}"),
        Step("click", selector="#a"),
        Step("fill", "#q", "{query}"),
        Step("press", "#q", "Enter"),
        Step("wait_for", selector="#b"),
        Step("pause"),
    )


def test_optional_results_default_blank():
    results = parse_ui_steps(MIN).results
    assert (results.error, results.no_results, results.next, results.next_disabled) == ("", "", "", "")


@pytest.mark.parametrize(
    "search,match",
    [
        ([{"hover": "#a"}], r"search\[1\]: unknown action 'hover'"),
        ([{"goto": "{url}"}, {"click": ""}], r"search\[2\]: 'click' needs a selector"),
        ([{"fill": {"selector": "#q"}}], r"search\[1\]\.value"),
        ([{"click": "#a", "goto": "{url}"}], r"search\[1\] must be one action"),
        ([], r"ui_steps\.search"),
        ([{"pause": "x"}], r"search\[1\]: 'pause' takes no value"),
    ],
)
def test_bad_step_is_named(search, match):
    with pytest.raises(ConfigError, match=match):
        parse_ui_steps({**MIN, "search": search})


def test_missing_results_key_is_named():
    raw = {**MIN, "results": {k: v for k, v in MIN["results"].items() if k != "done"}}
    with pytest.raises(ConfigError, match=r"ui_steps\.results\.done"):
        parse_ui_steps(raw)


def test_missing_file_is_config_error(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_ui_steps(tmp_path / "ui_steps.yaml")
