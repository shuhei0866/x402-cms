"""Per-run X API consumption counter.

X API bills pay-as-you-go, so every indexer run reports how much of
the budget it spent: requests issued, tweets read, and the latest
rate-limit headers per endpoint. The dollar figure is deliberately
not computed here — tier and rate card live in the X developer
dashboard, which is the source of truth for cost.

`_http` records each attempt before sending it and each response
before raising on its status, so a 429 or a read timeout still counts
as a call. Recording is best-effort: a malformed header or `meta`
field is noted in `record_errors` and never interrupts the run.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

# Endpoint keys used in the per-endpoint breakdown. X applies a
# separate rate-limit bucket to each, so the snapshots stay apart.
ENDPOINT_USER_LOOKUP = "users/by/username"
ENDPOINT_USER_TWEETS = "users/:id/tweets"

_RATE_LIMIT_HEADERS = {
    "limit": "x-rate-limit-limit",
    "remaining": "x-rate-limit-remaining",
    "reset": "x-rate-limit-reset",
}


def _header_int(response: httpx.Response, name: str) -> int | None:
    value = response.headers.get(name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _rate_limit_snapshot(response: httpx.Response) -> dict[str, Any] | None:
    """Read `x-rate-limit-*` into plain ints, or `None` if all absent."""
    snapshot: dict[str, Any] = {
        key: _header_int(response, header) for key, header in _RATE_LIMIT_HEADERS.items()
    }
    if all(v is None for v in snapshot.values()):
        return None
    snapshot["reset_at"] = None
    return snapshot


def _epoch_to_iso(seconds: int) -> str:
    """Raises on out-of-range epochs; callers run it under a guard."""
    return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class XApiUsage:
    """Mutable counter shared by every X API call in one indexer run.

    `calls_by_endpoint` counts attempts, including requests that ended
    in a transport error (`no_response`), because X may still have
    served and billed them. Every recorder swallows its own failures
    into `record_errors` / `last_record_error`: the tally must never
    be the reason a run stops.
    """

    calls_by_endpoint: dict[str, int] = field(default_factory=dict)
    no_response: int = 0
    tweets_read: int = 0
    rate_limits: dict[str, dict[str, Any]] = field(default_factory=dict)
    record_errors: int = 0
    last_record_error: str | None = None

    @property
    def api_calls(self) -> int:
        return sum(self.calls_by_endpoint.values())

    @contextmanager
    def _guard(self, what: str) -> Iterator[None]:
        try:
            yield
        except Exception as exc:  # the tally must never break the run
            self.record_errors += 1
            self.last_record_error = f"{what}: {type(exc).__name__}: {exc}"

    def record_attempt(self, endpoint: str) -> None:
        """Count one request, before it is sent."""
        with self._guard(f"attempt for {endpoint}"):
            self.calls_by_endpoint[endpoint] = self.calls_by_endpoint.get(endpoint, 0) + 1

    def record_no_response(self, endpoint: str) -> None:
        """Note that the attempt for `endpoint` raised before any response."""
        with self._guard(f"transport failure for {endpoint}"):
            self.no_response += 1

    def record_response(self, endpoint: str, response: httpx.Response) -> None:
        """Keep the response's rate-limit headers, if any."""
        with self._guard(f"rate-limit headers for {endpoint}"):
            snapshot = _rate_limit_snapshot(response)
            if snapshot is None:
                return
            self.rate_limits[endpoint] = snapshot
            if snapshot["reset"] is not None:
                # Separate step so a bad reset keeps limit / remaining.
                snapshot["reset_at"] = _epoch_to_iso(snapshot["reset"])

    def record_tweets(self, result_count: Any, *, fallback: int) -> None:
        """Add one page's `meta.result_count` (row count if absent / null)."""
        with self._guard("meta.result_count"):
            self.tweets_read += fallback if result_count is None else int(result_count)

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready view for the run summary."""
        return {
            "api_calls": self.api_calls,
            "calls_by_endpoint": dict(self.calls_by_endpoint),
            "no_response": self.no_response,
            "tweets_read": self.tweets_read,
            "rate_limits": {k: dict(v) for k, v in self.rate_limits.items()},
            "record_errors": self.record_errors,
            "last_record_error": self.last_record_error,
        }

    def summary_line(self) -> str:
        """One-line human summary for stderr / Cloud Logging."""
        head = f"X API usage: {self.api_calls} call(s)"
        details = [f"{k}={v}" for k, v in self.calls_by_endpoint.items()]
        if self.no_response:
            details.append(f"{self.no_response} without response")
        if details:
            head += f" ({', '.join(details)})"
        parts = [head, f"{self.tweets_read} tweet(s) read"]
        for endpoint, snap in self.rate_limits.items():
            parts.append(f"rate limit {endpoint}: {_format_rate_limit(snap)}")
        if self.record_errors:
            parts.append(
                f"{self.record_errors} usage record error(s), last: {self.last_record_error}"
            )
        return "; ".join(parts)


def _format_rate_limit(snap: dict[str, Any]) -> str:
    """Render only the fields the response actually carried."""
    remaining, limit = snap.get("remaining"), snap.get("limit")
    if remaining is not None and limit is not None:
        pieces = [f"{remaining}/{limit} remaining"]
    elif remaining is not None:
        pieces = [f"{remaining} remaining"]
    elif limit is not None:
        pieces = [f"limit {limit}"]
    else:
        pieces = []
    if snap.get("reset_at") is not None:
        pieces.append(f"resets {snap['reset_at']}")
    elif snap.get("reset") is not None:
        pieces.append(f"reset epoch {snap['reset']}")
    return ", ".join(pieces)
