"""Tests for `resolve_handle_to_id` — the @handle -> numeric id step.

This is the only network operation that maps a human-readable
identifier (what the curator types into `tracked_handles.yaml`) to the
identifier the X API actually accepts for tweet-fetch endpoints. The
function is the contract surface: bearer goes in the Authorization
header, handle reaches the `/2/users/by/username/...` path normalized
without a leading `@`, and the numeric id comes back as a string.

httpx.MockTransport is the injection seam: every request the function
issues lands in the handler, where the test can inspect the request
shape and decide which canned response to return.
"""

from __future__ import annotations

import httpx
import pytest

from code.indexers.x_indexer import HandleNotFoundError, resolve_handle_to_id

BEARER = "test-bearer"


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.x.com")


class TestResolveHandleToId:
    def test_returns_user_id_on_success(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["auth"] = request.headers.get("authorization")
            return httpx.Response(
                200,
                json={"data": {"id": "111222333", "username": "phdargen", "name": "x"}},
            )

        with _client(handler) as client:
            user_id = resolve_handle_to_id("phdargen", client=client, bearer=BEARER)

        assert user_id == "111222333"
        assert captured["auth"] == f"Bearer {BEARER}"
        assert "/2/users/by/username/phdargen" in captured["url"]

    def test_strips_leading_at_sign(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            return httpx.Response(200, json={"data": {"id": "1", "username": "phdargen"}})

        with _client(handler) as client:
            user_id = resolve_handle_to_id("@phdargen", client=client, bearer=BEARER)

        assert user_id == "1"
        # No literal "@" should appear in the path segment — X API
        # rejects "@" and would 404. Strip at the caller boundary.
        assert "@" not in captured["url"]

    def test_404_raises_handle_not_found(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                404,
                json={
                    "errors": [
                        {
                            "value": "doesnotexist",
                            "detail": "Could not find user with username: [doesnotexist].",
                        }
                    ]
                },
            )

        with _client(handler) as client:
            with pytest.raises(HandleNotFoundError):
                resolve_handle_to_id("doesnotexist", client=client, bearer=BEARER)

    def test_429_propagates_as_httpx_error(self) -> None:
        # Rate-limit surfaces as the usual httpx status error so the
        # orchestrator can decide whether to back off; the resolver
        # itself does not retry.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"title": "Too Many Requests"})

        with _client(handler) as client:
            with pytest.raises(httpx.HTTPStatusError):
                resolve_handle_to_id("phdargen", client=client, bearer=BEARER)
