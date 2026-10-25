"""Turn configured SPL templates into runnable queries (spec §5, query templating rules)."""

from __future__ import annotations

import re

from .config import SequenceCfg, SessionCfg

# Splunk's dedup drops events without the field; fill them first so a wrong
# session_id_field shows up as this value instead of as zero rows.
MISSING_SESSION_ID = "__NO_SESSION_ID__"


def escape_spl(value: str) -> str:
    """Escape a value for use inside an SPL double-quoted string."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _finalize(query: str) -> str:
    query = query.strip()
    if query.startswith("search ") or query.startswith("|"):
        return query
    return "search " + query


def render_session_query(cfg: SessionCfg, input_api: str) -> str:
    query = cfg.query.replace("{input_api}", escape_spl(input_api)).strip()
    field = cfg.session_id_field
    # head N+1: the fill row may take one slot; the runner trims back to N.
    query += f' | fillnull value="{MISSING_SESSION_ID}" {field} | dedup {field} | head {cfg.sessions_per_api + 1}'
    return _finalize(query)


def render_sequence_query(cfg: SequenceCfg, session_id: str) -> str:
    return _finalize(cfg.query.replace("{session_id}", escape_spl(session_id)))


# The last command is `table ...`: no pipe after the final "| table".
_ENDS_IN_TABLE = re.compile(r"\|\s*table\b[^|]*$")


def ensure_table(query: str) -> str:
    """End the query in a table command, so Splunk's Search page shows it as a Statistics table."""
    return query if _ENDS_IN_TABLE.search(query) else query + " | table *"
