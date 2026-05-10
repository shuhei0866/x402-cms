"""Structured access logging for the x402-cms server.

One FastAPI middleware emits a single JSON line per request to stdout
(`x402_cms.access` logger). Cloud Run picks up stdout JSON as
structured logs in Cloud Logging, so the same record is searchable both
locally and in production. The format is intentionally flat so the log
can be queried with simple field filters.

`configure_logging` rewires stdlib + uvicorn loggers through the same
JSON formatter, so unexpected exceptions and framework warnings land in
the same stream as access records — no parallel log dialects to chase.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from fastapi import Request, Response


class JSONFormatter(logging.Formatter):
    """Logging formatter that serialises each record as one JSON line.

    Records carrying an `event` dict via `extra={"event": ...}` have
    those fields merged into the top level, so access records keep the
    full request shape flat instead of nested.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": _now_iso(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        event = getattr(record, "event", None)
        if isinstance(event, dict):
            payload.update(event)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _now_iso() -> str:
    """ISO-8601 UTC timestamp with millisecond precision and a `Z` suffix."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def configure_logging(level: str = "INFO") -> None:
    """Wire stdlib + uvicorn loggers through `JSONFormatter` to stdout.

    Side effects: replaces handlers on the root logger and silences
    `uvicorn.access` so each request produces exactly one structured
    record (the one emitted by `access_log_middleware`), not two.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)

    uv_access = logging.getLogger("uvicorn.access")
    uv_access.handlers.clear()
    uv_access.propagate = False


_access_logger = logging.getLogger("x402_cms.access")


async def access_log_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Emit one JSON access record per request.

    Fields: ts, method, path, status, user_agent, audience, duration_ms.
    `audience` mirrors the same `is_agent_request` decision the handler
    used to dispatch the request, so a downstream consumer can filter
    on the audience the response was actually written for.
    """
    # Local import keeps `observability` independent from `dispatch`
    # at module load time (otherwise we'd add an import edge from a
    # logging utility into the application's dispatch logic).
    from code.dispatch import is_agent_request

    started = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - started) * 1000, 2)

    audience = "agent" if is_agent_request(request.headers) else "human"

    _access_logger.info(
        "access",
        extra={
            "event": {
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "user_agent": request.headers.get("user-agent", ""),
                "audience": audience,
                "duration_ms": duration_ms,
            }
        },
    )

    return response
