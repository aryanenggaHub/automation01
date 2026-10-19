"""Where the app keeps its files: next to the exe when packaged, else the current directory."""

from __future__ import annotations

import sys
from pathlib import Path


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path.cwd()


def resolve_in_app(p: str | Path) -> Path:
    path = Path(p)
    return path if path.is_absolute() else app_dir() / path
