"""Load and validate ui_steps.yaml: the screens and elements a search goes through (ADR 0003)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .config import ConfigError, _required_str, _section

UI_STEPS_NAME = "ui_steps.yaml"
ACTIONS = ("goto", "click", "fill", "press", "wait_for")


@dataclass(frozen=True)
class Step:
    action: str  # one of ACTIONS
    selector: str = ""  # element for click / fill / press / wait_for
    value: str = ""  # URL for goto, text for fill, key for press


@dataclass(frozen=True)
class ResultsCfg:
    done: str  # shown once the search job has finished
    table: str  # the results table
    header: str  # header cells inside the table; their text names the fields
    row: str  # result rows inside the table
    cell: str  # cells inside one row
    error: str = ""  # Splunk's error message for a failed search
    no_results: str = ""  # shown when the search found nothing
    next: str = ""  # Next-page control; blank means read one page only
    next_disabled: str = ""  # matches while Next can't be used (last page)


@dataclass(frozen=True)
class UiSteps:
    login_page: str  # only visible on the login page: detects an expired login
    search: tuple[Step, ...]
    results: ResultsCfg


def _optional_str(section: dict, prefix: str, key: str) -> str:
    value = section.get(key) or ""
    if not isinstance(value, str):
        raise ConfigError(f"Config key '{prefix}.{key}' must be a string")
    return value


def _step(raw, where: str) -> Step:
    if not isinstance(raw, dict) or len(raw) != 1:
        raise ConfigError(f"{where} must be one action: {', '.join(ACTIONS)}")
    action, arg = next(iter(raw.items()))
    if action not in ACTIONS:
        raise ConfigError(f"{where}: unknown action '{action}' (use {', '.join(ACTIONS)})")
    if action in ("goto", "click", "wait_for"):
        if not isinstance(arg, str) or not arg.strip():
            raise ConfigError(f"{where}: '{action}' needs a {'URL' if action == 'goto' else 'selector'}")
        return Step(action, value=arg) if action == "goto" else Step(action, selector=arg)
    second = "value" if action == "fill" else "key"
    if not isinstance(arg, dict):
        raise ConfigError(f"{where}: '{action}' needs selector and {second}")
    return Step(action, _required_str(arg, where, "selector"), _required_str(arg, where, second))


def parse_ui_steps(raw) -> UiSteps:
    if not isinstance(raw, dict):
        raise ConfigError("ui_steps.yaml must be a YAML mapping")
    search = raw.get("search")
    if not isinstance(search, list) or not search:
        raise ConfigError("Config key 'ui_steps.search' must be a list of steps")
    results = _section(raw, "results")
    p = "ui_steps.results"
    return UiSteps(
        login_page=_required_str(raw, "ui_steps", "login_page"),
        search=tuple(_step(s, f"ui_steps.search[{i}]") for i, s in enumerate(search, start=1)),
        results=ResultsCfg(
            done=_required_str(results, p, "done"),
            table=_required_str(results, p, "table"),
            header=_required_str(results, p, "header"),
            row=_required_str(results, p, "row"),
            cell=_required_str(results, p, "cell"),
            error=_optional_str(results, p, "error"),
            no_results=_optional_str(results, p, "no_results"),
            next=_optional_str(results, p, "next"),
            next_disabled=_optional_str(results, p, "next_disabled"),
        ),
    )


def load_ui_steps(path: Path) -> UiSteps:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"UI steps file not found: {path}") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"{Path(path).name} is not valid YAML: {exc}") from None
    return parse_ui_steps(raw)
