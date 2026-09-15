from __future__ import annotations

from collections import deque
import json
import logging
import os
import re
import threading
import time

from fastapi import FastAPI
from sqlalchemy import event
from sqlalchemy.engine import Engine

_LOG = logging.getLogger("scarletx.observability")
_TABLE_RE = re.compile(r"\b(?:FROM|INTO|UPDATE|JOIN)\s+[\"`\[]?([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)
_DB_TIMER_KEY = "_scarletx_observability_query_starts"


def _milliseconds(seconds: float) -> float:
    return round(max(0.0, float(seconds)) * 1000.0, 3)


def _average_ms(total_seconds: float, count: int) -> float:
    if count <= 0:
        return 0.0
    return _milliseconds(total_seconds / count)


class RuntimeObservability:
    """Small, bounded in-process runtime metrics collector.

    The collector deliberately stores aggregate counters rather than request
    payloads or SQL text. Slow-query history keeps only the SQL operation, one
    table token, and duration so credentials and user metadata cannot leak into
    diagnostics.
    """

    def __init__(
        self,
        *,
        slow_query_ms: float | None = None,
        slow_query_history: int = 20,
    ) -> None:
        if slow_query_ms is None:
            try:
                slow_query_ms = float(os.getenv("SCARLETX_SLOW_QUERY_MS", "250"))
            except ValueError:
                slow_query_ms = 250.0
        self.slow_query_ms = max(0.0, float(slow_query_ms))
        self._lock = threading.Lock()
        self._request_count = 0
        self._request_errors = 0
        self._request_total_seconds = 0.0
        self._request_max_seconds = 0.0
        self._db_count = 0
        self._db_slow_count = 0
        self._db_total_seconds = 0.0
        self._db_max_seconds = 0.0
        self._slow_queries: deque[dict[str, object]] = deque(maxlen=max(1, int(slow_query_history)))
        self._tpdb_network_requests = 0
        self._tpdb_network_failures = 0
        self._tpdb_network_total_seconds = 0.0
        self._tpdb_network_max_seconds = 0.0
        self._tpdb_cache_hits = {"memory": 0, "disk": 0}

    def record_request(
        self,
        method: str,
        path: str,
        status_code: int,
        elapsed_seconds: float,
    ) -> None:
        del method, path
        elapsed = max(0.0, float(elapsed_seconds))
        with self._lock:
            self._request_count += 1
            self._request_errors += int(status_code >= 500)
            self._request_total_seconds += elapsed
            self._request_max_seconds = max(self._request_max_seconds, elapsed)

    def record_db_query(self, statement: str, elapsed_seconds: float) -> None:
        elapsed = max(0.0, float(elapsed_seconds))
        stripped = statement.lstrip()
        operation = (stripped.split(None, 1)[0].upper() if stripped else "UNKNOWN")[:16]
        match = _TABLE_RE.search(statement)
        table = match.group(1) if match else "unknown"
        duration_ms = _milliseconds(elapsed)
        slow_record: dict[str, object] | None = None
        with self._lock:
            self._db_count += 1
            self._db_total_seconds += elapsed
            self._db_max_seconds = max(self._db_max_seconds, elapsed)
            if duration_ms >= self.slow_query_ms:
                self._db_slow_count += 1
                slow_record = {
                    "operation": operation,
                    "table": table,
                    "duration_ms": duration_ms,
                }
                self._slow_queries.append(slow_record)
        if slow_record is not None:
            try:
                _LOG.warning(json.dumps({"event": "slow_query", **slow_record}, separators=(",", ":")))
            except Exception:
                pass

    def record_tpdb(self, elapsed_seconds: float, *, success: bool, cache: str) -> None:
        elapsed = max(0.0, float(elapsed_seconds))
        with self._lock:
            if cache == "network":
                self._tpdb_network_requests += 1
                self._tpdb_network_failures += int(not success)
                self._tpdb_network_total_seconds += elapsed
                self._tpdb_network_max_seconds = max(self._tpdb_network_max_seconds, elapsed)
            elif cache in self._tpdb_cache_hits:
                self._tpdb_cache_hits[cache] += 1

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "requests": {
                    "count": self._request_count,
                    "errors": self._request_errors,
                    "avg_ms": _average_ms(self._request_total_seconds, self._request_count),
                    "max_ms": _milliseconds(self._request_max_seconds),
                },
                "database": {
                    "count": self._db_count,
                    "slow_count": self._db_slow_count,
                    "avg_ms": _average_ms(self._db_total_seconds, self._db_count),
                    "max_ms": _milliseconds(self._db_max_seconds),
                    "recent_slow_queries": list(self._slow_queries),
                },
                "tpdb": {
                    "network_requests": self._tpdb_network_requests,
                    "network_failures": self._tpdb_network_failures,
                    "network_avg_ms": _average_ms(
                        self._tpdb_network_total_seconds,
                        self._tpdb_network_requests,
                    ),
                    "network_max_ms": _milliseconds(self._tpdb_network_max_seconds),
                    "cache_hits": dict(self._tpdb_cache_hits),
                },
            }


runtime_observability = RuntimeObservability()


def install_observability(app: FastAPI, engine: Engine) -> None:
    """Install low-overhead request and SQL timing exactly once."""

    if not getattr(app.state, "scarletx_observability_installed", False):
        @app.middleware("http")
        async def _observe_request(request, call_next):
            started = time.perf_counter()
            status_code = 500
            try:
                response = await call_next(request)
                status_code = response.status_code
                return response
            finally:
                try:
                    runtime_observability.record_request(
                        request.method,
                        request.url.path,
                        status_code,
                        time.perf_counter() - started,
                    )
                except Exception:
                    pass

        app.state.scarletx_observability_installed = True

    if getattr(engine, "_scarletx_observability_installed", False):
        return

    @event.listens_for(engine, "before_cursor_execute")
    def _before_cursor_execute(conn, _cursor, _statement, _parameters, _context, _executemany):
        try:
            conn.info.setdefault(_DB_TIMER_KEY, []).append(time.perf_counter())
        except Exception:
            pass

    @event.listens_for(engine, "after_cursor_execute")
    def _after_cursor_execute(conn, _cursor, statement, _parameters, _context, _executemany):
        try:
            starts = conn.info.get(_DB_TIMER_KEY) or []
            if not starts:
                return
            started = starts.pop()
            runtime_observability.record_db_query(statement, time.perf_counter() - started)
        except Exception:
            pass

    @event.listens_for(engine, "handle_error")
    def _handle_cursor_error(exception_context):
        try:
            conn = exception_context.connection
            if conn is None:
                return
            starts = conn.info.get(_DB_TIMER_KEY) or []
            if not starts:
                return
            started = starts.pop()
            statement = getattr(exception_context, "statement", None) or "UNKNOWN"
            runtime_observability.record_db_query(statement, time.perf_counter() - started)
        except Exception:
            pass

    setattr(engine, "_scarletx_observability_installed", True)
