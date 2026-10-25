"""Command-line entry point (spec §4)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import ConfigError, load_config, with_overrides
from .job import execute


def load_input_apis(text: str) -> tuple[list[str], int]:
    """Return (unique Input APIs in order, number of duplicates skipped)."""
    lines = [line.strip() for line in text.splitlines()]
    kept = [line for line in lines if line and not line.startswith("#")]
    apis = list(dict.fromkeys(kept))
    return apis, len(kept) - len(apis)


def confirm_in_console(timeout_s: float) -> bool:
    """Wait for Enter (the timeout doesn't apply: Ctrl+C cancels)."""
    try:
        input("Press Enter here once you are logged in to Splunk... ")
    except EOFError:
        return False
    return True


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


def main(argv: list[str] | None = None) -> int:
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
        apis, skipped = load_input_apis(text)
        if skipped:
            print(f"Warning: {skipped} duplicate Input API line(s) skipped")
    else:
        apis = [args.api.strip()]
    if not apis:
        return _error("no Input APIs to process")

    cfg = with_overrides(cfg, args.earliest, args.latest)

    return execute(cfg, apis, print, confirm_in_console).exit_code
