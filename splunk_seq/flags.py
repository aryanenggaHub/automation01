"""Per-row Flags for one Session's API Sequence (spec §9)."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from .config import SequenceCfg
from .models import AMBIGUOUS, BAD_TIMESTAMP, UNKNOWN_LAYER, Row


def _filled(value) -> bool:
    return value is not None and str(value).strip() != ""


def compute_flags(rows: list[Row], cfg: SequenceCfg) -> list[str]:
    flags = [""] * len(rows)
    window = timedelta(milliseconds=cfg.ambiguity_window_ms)
    by_layer: dict[str, list[tuple[datetime, int]]] = defaultdict(list)

    for i, row in enumerate(rows):
        layers = [name for name, col in cfg.layer_columns.items() if _filled(row.get(col))]
        if len(layers) != 1:
            flags[i] = UNKNOWN_LAYER
            continue
        try:
            ts = datetime.strptime(str(row.get(cfg.timestamp_field, "")).strip(), cfg.timestamp_format)
        except ValueError:
            flags[i] = BAD_TIMESTAMP
            continue
        by_layer[layers[0]].append((ts, i))

    for calls in by_layer.values():
        calls.sort()
        for (t1, i1), (t2, i2) in zip(calls, calls[1:]):
            if t2 - t1 <= window:
                flags[i1] = flags[i2] = AMBIGUOUS
    return flags
