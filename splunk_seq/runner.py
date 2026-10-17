"""Process every Input API and write each result as it finishes (spec §6 step 5)."""

from __future__ import annotations

from typing import Callable

from .config import Config
from .errors import SearchError
from .flags import compute_flags
from .models import ERROR, NO_SESSION, OK, ApiResult, SearchFn, SessionResult
from .queries import render_sequence_query, render_session_query


def _session_ids(rows, field: str) -> list[str]:
    ids = [r[field] for r in rows if r.get(field)]
    if rows and not ids:
        raise SearchError(f"Session Query results have no '{field}' field")
    return list(dict.fromkeys(ids))


def _process(api: str, cfg: Config, search: SearchFn, log: Callable[[str], None]) -> ApiResult:
    result = ApiResult(input_api=api, status=OK)
    earliest, latest = cfg.search.earliest, cfg.search.latest
    try:
        rows = search(render_session_query(cfg.session, api), earliest, latest)
        ids = _session_ids(rows, cfg.session.session_id_field)
        if not ids:
            result.status = NO_SESSION
            return result
        for sid in ids:
            seq = search(render_sequence_query(cfg.sequence, sid), earliest, latest)
            result.sessions.append(SessionResult(sid, seq, compute_flags(seq, cfg.sequence)))
            log(f"  session {sid}: {len(seq)} rows")
    except Exception as exc:  # any failure ends this API only; the run continues
        result.status = ERROR
        result.error = str(exc) or type(exc).__name__
    return result


def run(apis: list[str], cfg: Config, search: SearchFn, workbook, log: Callable[[str], None] = print) -> dict[str, int]:
    tally = {OK: 0, NO_SESSION: 0, ERROR: 0}
    for i, api in enumerate(apis, start=1):
        log(f"[{i}/{len(apis)}] {api}")
        result = _process(api, cfg, search, log)
        workbook.add(i, result)
        workbook.save()
        tally[result.status] += 1
        log(f"  {result.status}" + (f": {result.error}" if result.error else ""))
    return tally
