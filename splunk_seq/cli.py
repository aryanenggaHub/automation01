"""Command-line entry point (spec §4)."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from .browser import BrowserSession
from .config import ConfigError, load_config, with_overrides
from .fetch import AutoFetcher, UiFetcher, with_relogin
from .fetch_proxy import ProxyFetcher
from .runner import run
from .workbook import SequenceWorkbook, output_path


def load_input_apis(text: str) -> tuple[list[str], list[str]]:
    apis: list[str] = []
    duplicates: list[str] = []
    for line in text.splitlines():
        api = line.strip()
        if not api or api.startswith("#"):
            continue
        (duplicates if api in apis else apis).append(api)
    return apis, duplicates


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="splunk_seq", description="Rebuild API Sequences from Splunk into Excel.")
    commands = parser.add_subparsers(dest="command", required=True)
    run_cmd = commands.add_parser("run", help="analyse one Input API or a file of them")
    source = run_cmd.add_mutually_exclusive_group(required=True)
    source.add_argument("--api", help="a single Input API")
    source.add_argument("--file", help="text file, one Input API per line (# for comments)")
    run_cmd.add_argument("--config", default="config.yaml", help="config file (default: config.yaml)")
    run_cmd.add_argument("--earliest", help="override search.earliest for this run")
    run_cmd.add_argument("--latest", help="override search.latest for this run")
    return parser


def _error(message: str) -> int:
    print(f"Error: {message}", file=sys.stderr)
    return 1


def _join_time_values(argv: list[str]) -> list[str]:
    """Let `--earliest -1h` work: argparse would read the Splunk time `-1h` as an option."""
    joined: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] in ("--earliest", "--latest") and i + 1 < len(argv):
            joined.append(f"{argv[i]}={argv[i + 1]}")
            i += 2
        else:
            joined.append(argv[i])
            i += 1
    return joined


def main(argv: list[str] | None = None) -> int:
    argv = _join_time_values(sys.argv[1:] if argv is None else argv)
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return 0 if exc.code in (0, None) else 1

    try:
        cfg = load_config(Path(args.config))
    except ConfigError as exc:
        return _error(str(exc))

    if args.file:
        try:
            text = Path(args.file).read_text(encoding="utf-8-sig")
        except OSError as exc:
            return _error(f"cannot read input file {args.file}: {exc.strerror or exc}")
        apis, duplicates = load_input_apis(text)
        for dup in dict.fromkeys(duplicates):
            print(f"Warning: duplicate Input API skipped: {dup}")
    else:
        apis = [args.api.strip()]
    if not apis:
        return _error("no Input APIs to process")

    cfg = with_overrides(cfg, args.earliest, args.latest)

    with BrowserSession(cfg) as session:
        if not session.wait_for_login():
            print("Error: login was not detected in time", file=sys.stderr)
            return 2
        proxy = ProxyFetcher(cfg, session.post, session.cookies).run_search
        ui = UiFetcher(session.page).run_search
        search = {"proxy": proxy, "ui": ui}.get(cfg.fetch_mode) or AutoFetcher(proxy, ui, print).run_search
        search = with_relogin(search, session.wait_for_login, print)

        path = output_path(cfg.output, datetime.now())
        tally = run(apis, cfg, search, SequenceWorkbook(path, len(apis)))

    print(f"Wrote {path}")
    print(" ".join(f"{status}={count}" for status, count in tally.items()))
    return 0
