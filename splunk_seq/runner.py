"""Process every Input API and write each result as it finishes (spec §6 step 5)."""

from __future__ import annotations

from typing import Callable

from .config import Config
from .errors import SearchError
from .flags import compute_flags
from .models import ERROR, NO_SESSION, OK, ApiResult, SearchFn, SessionResult
from .queries import MISSING_SESSION_ID, render_sequence_query, render_session_query


def _session_ids(rows, field: str, limit: int) -> list[str]:
    ids = [r[field] for r in rows if r.get(field) and r[field] != MISSING_SESSION_ID]
    if rows and not ids:
        raise SearchError(f"Session Query results have no '{field}' field")
    return list(dict.fromkeys(ids))[:limit]


def _process(api: str, cfg: Config, search: SearchFn, log: Callable[[str], None]) -> ApiResult:
    result = ApiResult(input_api=api, status=OK)
    earliest, latest = cfg.search.earliest, cfg.search.latest
    try:
        rows = search(render_session_query(cfg.session, api), earliest, latest)
        ids = _session_ids(rows, cfg.session.session_id_field, cfg.session.sessions_per_api)
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
    saved = True
    for i, api in enumerate(apis, start=1):
        log(f"[{i}/{len(apis)}] {api}")
        result = _process(api, cfg, search, log)
        workbook.add(i, result)
        saved = _try_save(workbook, log)
        tally[result.status] += 1
        log(f"  {result.status}" + (f": {result.error}" if result.error else ""))
    if not saved:
        _try_save(workbook, log)
    return tally


def _try_save(workbook, log: Callable[[str], None]) -> bool:
    try:
        workbook.save()
        return True
    except OSError as exc:
        log(f"  Warning: could not save the workbook ({exc}); is it open in Excel? Will retry on the next save.")
        return False
