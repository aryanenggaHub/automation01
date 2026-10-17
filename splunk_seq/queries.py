"""Turn configured SPL templates into runnable queries (spec §5, query templating rules)."""

from __future__ import annotations

from .config import SequenceCfg, SessionCfg


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
    query += f" | dedup {cfg.session_id_field} | head {cfg.sessions_per_api}"
    return _finalize(query)


def render_sequence_query(cfg: SequenceCfg, session_id: str) -> str:
    return _finalize(cfg.query.replace("{session_id}", escape_spl(session_id)))
