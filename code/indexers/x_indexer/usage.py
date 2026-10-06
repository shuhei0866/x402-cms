"""Per-run X API consumption counter.

X API bills pay-as-you-go, so every indexer run reports how much of
the budget it spent: requests issued, tweets read, and the latest
rate-limit headers per endpoint. The dollar figure is deliberately
not computed here — tier and rate card live in the X developer
dashboard, which is the source of truth for cost.

`_http` records each response into an `XApiUsage` before raising on
its status, so a 429 still counts as a call and still surfaces the
rate-limit snapshot that explains it.
"""

from __future__ import annotations

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
    reset = snapshot["reset"]
    snapshot["reset_at"] = (
        datetime.fromtimestamp(reset, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if reset is not None
        else None
    )
    return snapshot


@dataclass
class XApiUsage:
    """Mutable counter shared by every X API call in one indexer run."""

    calls_by_endpoint: dict[str, int] = field(default_factory=dict)
    tweets_read: int = 0
    rate_limits: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def api_calls(self) -> int:
        return sum(self.calls_by_endpoint.values())

    def record_response(self, endpoint: str, response: httpx.Response) -> None:
        """Count one request and keep its rate-limit headers, if any."""
        self.calls_by_endpoint[endpoint] = self.calls_by_endpoint.get(endpoint, 0) + 1
        snapshot = _rate_limit_snapshot(response)
        if snapshot is not None:
            self.rate_limits[endpoint] = snapshot

    def record_tweets(self, count: int) -> None:
        self.tweets_read += count

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready view for the run summary."""
        return {
            "api_calls": self.api_calls,
            "calls_by_endpoint": dict(self.calls_by_endpoint),
            "tweets_read": self.tweets_read,
            "rate_limits": {k: dict(v) for k, v in self.rate_limits.items()},
        }

    def summary_line(self) -> str:
        """One-line human summary for stderr / Cloud Logging."""
        parts = [f"X API usage: {self.api_calls} call(s)"]
        if self.calls_by_endpoint:
            breakdown = ", ".join(f"{k}={v}" for k, v in self.calls_by_endpoint.items())
            parts[0] += f" ({breakdown})"
        parts.append(f"{self.tweets_read} tweet(s) read")
        for endpoint, snap in self.rate_limits.items():
            parts.append(
                f"rate limit {endpoint}: {snap['remaining']}/{snap['limit']} "
                f"remaining, resets {snap['reset_at']}"
            )
        return "; ".join(parts)
