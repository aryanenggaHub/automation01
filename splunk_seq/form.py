"""The settings form as data: which fields exist and how they map to config.yaml (standalone spec §8)."""

from __future__ import annotations

import copy
from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    key: str  # dotted path into the raw config dict
    label: str
    kind: str  # text | multiline | int | bool | choice | file | dir
    advanced: bool = False


CHANNEL_LABELS = {"chrome": "Chrome", "msedge": "Edge"}

_LAYERS = "sequence.layer_columns."

FIELDS = [
    Field("browser.channel", "Browser", "choice"),
    Field("splunk.url", "Splunk URL", "text"),
    Field("search.earliest", "Earliest", "text"),
    Field("search.latest", "Latest", "text"),
    Field("session.sessions_per_api", "Sessions per API", "int"),
    Field("session.query", "Session Query", "multiline"),
    Field("sequence.query", "Sequence Query", "multiline"),
    Field("output.dir", "Output folder", "dir"),
    Field("session.session_id_field", "Session ID field", "text", True),
    Field("sequence.timestamp_field", "Timestamp field", "text", True),
    Field("sequence.timestamp_format", "Timestamp format", "text", True),
    Field("sequence.ambiguity_window_ms", "Ambiguity window (ms)", "int", True),
    Field(_LAYERS + "Gateway", "Gateway column", "text", True),
    Field(_LAYERS + "Microservice", "Microservice column", "text", True),
    Field(_LAYERS + "Downstream API", "Downstream API column", "text", True),
    Field(_LAYERS + "Downstream MQ", "Downstream MQ column", "text", True),
    Field("browser.ca_cert_file", "Company CA certificate (.pem)", "file", True),
    Field("browser.ignore_https_errors", "Ignore HTTPS errors", "bool", True),
]


def _get(raw: dict, key: str):
    node = raw
    for part in key.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def raw_to_form(raw: dict) -> dict[str, str | bool]:
    values: dict[str, str | bool] = {}
    for field in FIELDS:
        value = _get(raw, field.key)
        values[field.key] = bool(value) if field.kind == "bool" else ("" if value is None else str(value))
    return values


def form_to_raw(values: dict[str, str | bool], base: dict) -> dict:
    raw = copy.deepcopy(base)
    for field in FIELDS:
        value = values[field.key]
        if field.kind == "int" and str(value).strip().isdigit():
            value = int(str(value).strip())
        elif field.kind == "bool":
            value = bool(value)
        *parents, last = field.key.split(".")
        node = raw
        for part in parents:
            if not isinstance(node.get(part), dict):
                node[part] = {}
            node = node[part]
        node[last] = value
    return raw
