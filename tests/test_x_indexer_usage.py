"""Tests for per-run X API consumption tracking.

What we lock in:

- Every request counts as one call, per endpoint (handle lookups vs
  timeline pages), including pagination requests and requests that
  ended in a transport error (also counted under `no_response`).
- Tweets read is the sum of `meta.result_count` across pages.
- A failed request (429, 404) is still counted, and its rate-limit
  headers are still captured, because the counter records before the
  status check raises.
- Rate-limit snapshots are kept per endpoint, latest response wins.
- `run_for_week` surfaces the tally under `api_usage`, and a caller
  that injects its own counter can read it after the run raises.
- Omitting `usage` leaves the network functions' behaviour unchanged.
- Malformed usage inputs (null `result_count`, out-of-range
  `x-rate-limit-reset`) are noted in `record_errors` and never stop
  the run.
- The CLI prints the summary to stderr on success and on failure, and
  the stdout JSON carries `api_usage`.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock

import httpx
import pytest

from code.indexers.x_indexer import __main__ as cli
from code.indexers.x_indexer import (
    HandleNotFoundError,
    XApiUsage,
    fetch_user_tweets,
    resolve_handle_to_id,
    run_for_week,
)

START = datetime(2026, 5, 4, 0, 0, tzinfo=timezone.utc)
END = datetime(2026, 5, 11, 0, 0, tzinfo=timezone.utc)
LOOKUP = "users/by/username"
TWEETS = "users/:id/tweets"


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _rl(limit: int, remaining: int, reset: int) -> dict[str, str]:
    return {
        "x-rate-limit-limit": str(limit),
        "x-rate-limit-remaining": str(remaining),
        "x-rate-limit-reset": str(reset),
    }


def _row(post_id: str) -> dict:
    return {
        "id": post_id,
        "text": f"tweet {post_id}",
        "created_at": "2026-05-05T12:00:00.000Z",
        "conversation_id": post_id,
    }


class TestFetchUserTweetsUsage:
    def test_counts_each_page_and_sums_result_count(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            token = request.url.params.get("pagination_token")
            if token is None:
                return httpx.Response(
                    200,
                    json={
                        "data": [_row("1"), _row("2")],
                        "meta": {"result_count": 2, "next_token": "T2"},
                    },
                    headers=_rl(1500, 1499, 1778000000),
                )
            return httpx.Response(
                200,
                json={"data": [_row("3")], "meta": {"result_count": 1}},
                headers=_rl(1500, 1498, 1778000000),
            )

        usage = XApiUsage()
        with _client(handler) as client:
            posts = fetch_user_tweets(
                user_id="1",
                handle="x",
                start=START,
                end=END,
                client=client,
                bearer="t",
                usage=usage,
            )

        assert len(posts) == 3
        assert usage.api_calls == 2
        assert usage.calls_by_endpoint == {TWEETS: 2}
        assert usage.tweets_read == 3
        # Latest page's headers win.
        assert usage.rate_limits[TWEETS]["remaining"] == 1498
        assert usage.rate_limits[TWEETS]["limit"] == 1500
        assert usage.rate_limits[TWEETS]["reset"] == 1778000000
        assert usage.rate_limits[TWEETS]["reset_at"] == "2026-05-05T16:53:20Z"

    def test_empty_page_counts_call_but_no_tweets(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"meta": {"result_count": 0}})

        usage = XApiUsage()
        with _client(handler) as client:
            fetch_user_tweets(
                user_id="1",
                handle="x",
                start=START,
                end=END,
                client=client,
                bearer="t",
                usage=usage,
            )

        assert usage.api_calls == 1
        assert usage.tweets_read == 0
        # No rate-limit headers on the response -> no snapshot.
        assert usage.rate_limits == {}

    def test_missing_meta_falls_back_to_row_count(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [_row("1"), _row("2")]})

        usage = XApiUsage()
        with _client(handler) as client:
            fetch_user_tweets(
                user_id="1",
                handle="x",
                start=START,
                end=END,
                client=client,
                bearer="t",
                usage=usage,
            )

        assert usage.tweets_read == 2

    def test_429_is_counted_and_headers_captured_before_raising(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                429,
                json={"title": "Too Many Requests"},
                headers=_rl(1500, 0, 1778000900),
            )

        usage = XApiUsage()
        with _client(handler) as client:
            with pytest.raises(httpx.HTTPStatusError):
                fetch_user_tweets(
                    user_id="1",
                    handle="x",
                    start=START,
                    end=END,
                    client=client,
                    bearer="t",
                    usage=usage,
                )

        assert usage.api_calls == 1
        assert usage.tweets_read == 0
        assert usage.rate_limits[TWEETS]["remaining"] == 0


class TestResolveHandleUsage:
    def test_lookup_is_counted_with_headers(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"data": {"id": "1"}}, headers=_rl(300, 299, 1778000000)
            )

        usage = XApiUsage()
        with _client(handler) as client:
            assert resolve_handle_to_id("a", client=client, bearer="t", usage=usage) == "1"

        assert usage.calls_by_endpoint == {LOOKUP: 1}
        assert usage.rate_limits[LOOKUP]["remaining"] == 299

    def test_404_still_counts_as_a_call(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"errors": [{"detail": "not found"}]})

        usage = XApiUsage()
        with _client(handler) as client:
            with pytest.raises(HandleNotFoundError):
                resolve_handle_to_id("nope", client=client, bearer="t", usage=usage)

        assert usage.api_calls == 1

    def test_without_usage_behaviour_is_unchanged(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": {"id": "42"}})

        with _client(handler) as client:
            assert resolve_handle_to_id("a", client=client, bearer="t") == "42"


class TestRunForWeekUsage:
    @staticmethod
    def _handler(request: httpx.Request) -> httpx.Response:
        # Two handles; `b` has two timeline pages.
        path = request.url.path
        if "/by/username/" in path:
            handle = path.rsplit("/", 1)[-1]
            return httpx.Response(
                200,
                json={"data": {"id": {"a": "1", "b": "2"}[handle]}},
                headers=_rl(300, 290 if handle == "a" else 289, 1778000000),
            )
        user_id = path.split("/2/users/")[1].split("/tweets")[0]
        token = request.url.params.get("pagination_token")
        if user_id == "2" and token is None:
            return httpx.Response(
                200,
                json={
                    "data": [_row("b1"), _row("b2")],
                    "meta": {"result_count": 2, "next_token": "N"},
                },
                headers=_rl(1500, 1498, 1778000500),
            )
        if user_id == "2":
            return httpx.Response(
                200,
                json={"data": [_row("b3")], "meta": {"result_count": 1}},
                headers=_rl(1500, 1497, 1778000500),
            )
        return httpx.Response(
            200,
            json={"data": [_row("a1")], "meta": {"result_count": 1}},
            headers=_rl(1500, 1499, 1778000500),
        )

    def test_result_carries_api_usage(self) -> None:
        with _client(self._handler) as client:
            result = run_for_week(
                week="2026-W19",
                handles=["a", "b"],
                bearer="t",
                client=client,
                fs_client=MagicMock(),
            )

        api_usage = result["api_usage"]
        # 2 resolves + 1 fetch for `a` + 2 pages for `b`.
        assert api_usage["api_calls"] == 5
        assert api_usage["calls_by_endpoint"] == {LOOKUP: 2, TWEETS: 3}
        assert api_usage["tweets_read"] == 4
        assert api_usage["rate_limits"][LOOKUP]["remaining"] == 289
        assert api_usage["rate_limits"][TWEETS]["remaining"] == 1497
        # The CLI prints the result with json.dumps; it must stay serialisable.
        json.dumps(result)

    def test_dry_run_also_reports_usage(self) -> None:
        with _client(self._handler) as client:
            result = run_for_week(
                week="2026-W19",
                handles=["a"],
                bearer="t",
                client=client,
                fs_client=MagicMock(),
                dry_run=True,
            )

        assert result["api_usage"]["api_calls"] == 2
        assert result["api_usage"]["tweets_read"] == 1

    def test_injected_usage_survives_a_mid_run_failure(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if "/by/username/" in request.url.path:
                return httpx.Response(200, json={"data": {"id": "1"}})
            return httpx.Response(429, headers=_rl(1500, 0, 1778000900))

        usage = XApiUsage()
        with _client(handler) as client:
            with pytest.raises(httpx.HTTPStatusError):
                run_for_week(
                    week="2026-W19",
                    handles=["a"],
                    bearer="t",
                    client=client,
                    fs_client=MagicMock(),
                    usage=usage,
                )

        assert usage.api_calls == 2
        assert usage.rate_limits[TWEETS]["remaining"] == 0


class TestRecordingNeverStopsTheRun:
    def test_null_result_count_falls_back_to_row_count(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"data": [_row("1"), _row("2")], "meta": {"result_count": None}}
            )

        usage = XApiUsage()
        with _client(handler) as client:
            posts = fetch_user_tweets(
                user_id="1",
                handle="x",
                start=START,
                end=END,
                client=client,
                bearer="t",
                usage=usage,
            )

        assert len(posts) == 2
        assert usage.tweets_read == 2
        assert usage.record_errors == 0

    def test_unparseable_result_count_is_noted_not_raised(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"data": [_row("1")], "meta": {"result_count": {"n": 1}}}
            )

        usage = XApiUsage()
        with _client(handler) as client:
            posts = fetch_user_tweets(
                user_id="1",
                handle="x",
                start=START,
                end=END,
                client=client,
                bearer="t",
                usage=usage,
            )

        assert len(posts) == 1
        assert usage.tweets_read == 0
        assert usage.record_errors == 1
        assert "result_count" in usage.last_record_error

    def test_out_of_range_rate_limit_reset_is_noted_not_raised(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if "/by/username/" in request.url.path:
                return httpx.Response(
                    200,
                    json={"data": {"id": "1"}},
                    headers=_rl(300, 299, 10**20),
                )
            return httpx.Response(
                200,
                json={"data": [_row("a1")], "meta": {"result_count": None}},
                headers=_rl(1500, 1499, 10**20),
            )

        usage = XApiUsage()
        with _client(handler) as client:
            result = run_for_week(
                week="2026-W19",
                handles=["a"],
                bearer="t",
                client=client,
                fs_client=MagicMock(),
                usage=usage,
            )

        assert result["posts_fetched"] == 1
        assert result["posts_written"] == 1
        api_usage = result["api_usage"]
        assert api_usage["api_calls"] == 2
        assert api_usage["tweets_read"] == 1
        # limit / remaining survive; only the unconvertible reset is dropped.
        assert api_usage["rate_limits"][TWEETS]["remaining"] == 1499
        assert api_usage["rate_limits"][TWEETS]["reset_at"] is None
        assert api_usage["record_errors"] == 2
        assert "rate-limit headers" in api_usage["last_record_error"]
        json.dumps(result)


class TestTransportFailures:
    def test_read_timeout_counts_as_an_attempt_without_response(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if "/by/username/" in request.url.path:
                return httpx.Response(200, json={"data": {"id": "1"}})
            raise httpx.ReadTimeout("timed out", request=request)

        usage = XApiUsage()
        with _client(handler) as client:
            with pytest.raises(httpx.ReadTimeout):
                run_for_week(
                    week="2026-W19",
                    handles=["a"],
                    bearer="t",
                    client=client,
                    fs_client=MagicMock(),
                    usage=usage,
                )

        assert usage.api_calls == 2
        assert usage.calls_by_endpoint == {LOOKUP: 1, TWEETS: 1}
        assert usage.no_response == 1
        assert "1 without response" in usage.summary_line()


class TestSummaryLine:
    def test_summary_line_mentions_calls_tweets_and_rate_limits(self) -> None:
        usage = XApiUsage()
        usage.record_attempt(TWEETS)
        usage.record_response(TWEETS, httpx.Response(200, headers=_rl(1500, 1400, 0)))
        usage.record_tweets(7, fallback=0)

        line = usage.summary_line()

        assert line.startswith("X API usage: 1 call(s)")
        assert f"{TWEETS}=1" in line
        assert "7 tweet(s) read" in line
        assert "1400/1500 remaining" in line
        assert "1970-01-01T00:00:00Z" in line

    def test_summary_line_with_no_calls(self) -> None:
        assert XApiUsage().summary_line() == "X API usage: 0 call(s); 0 tweet(s) read"

    def test_missing_header_values_are_left_out(self) -> None:
        usage = XApiUsage()
        usage.record_response(TWEETS, httpx.Response(200, headers={"x-rate-limit-limit": "1500"}))
        usage.record_response(LOOKUP, httpx.Response(200, headers={"x-rate-limit-remaining": "12"}))

        line = usage.summary_line()

        assert "None" not in line
        assert f"rate limit {TWEETS}: limit 1500" in line
        assert f"rate limit {LOOKUP}: 12 remaining" in line
        assert "resets" not in line

    def test_record_errors_are_surfaced(self) -> None:
        usage = XApiUsage()
        usage.record_tweets("not a number", fallback=0)

        assert "1 usage record error(s)" in usage.summary_line()


class TestCli:
    """`python -m code.indexers.x_indexer` end to end, HTTP mocked."""

    @staticmethod
    def _run(monkeypatch, tmp_path, handler) -> int:
        handles = tmp_path / "tracked_handles.yaml"
        handles.write_text("- a\n")
        monkeypatch.setenv("X_BEARER_TOKEN", "t")
        monkeypatch.setattr(
            sys,
            "argv",
            ["x_indexer", "--handles-config", str(handles), "--week", "2026-W19", "--dry-run"],
        )

        real_client = httpx.Client

        def fake_client(**_kwargs) -> httpx.Client:
            return real_client(transport=httpx.MockTransport(handler))

        monkeypatch.setattr(cli.httpx, "Client", fake_client)
        return cli.main()

    def test_success_prints_summary_and_api_usage(self, monkeypatch, tmp_path, capsys) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if "/by/username/" in request.url.path:
                return httpx.Response(200, json={"data": {"id": "1"}})
            return httpx.Response(
                200,
                json={"data": [_row("a1")], "meta": {"result_count": 1}},
                headers=_rl(1500, 1499, 1778000000),
            )

        assert self._run(monkeypatch, tmp_path, handler) == 0

        out, err = capsys.readouterr()
        result = json.loads(out)
        assert result["api_usage"]["api_calls"] == 2
        assert result["api_usage"]["tweets_read"] == 1
        assert (
            "X API usage: 2 call(s) (users/by/username=1, users/:id/tweets=1); "
            "1 tweet(s) read; rate limit users/:id/tweets: 1499/1500 remaining, "
            "resets 2026-05-05T16:53:20Z"
        ) in err

    def test_failure_mid_run_still_prints_summary(self, monkeypatch, tmp_path, capsys) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if "/by/username/" in request.url.path:
                return httpx.Response(200, json={"data": {"id": "1"}})
            return httpx.Response(429, headers=_rl(1500, 0, 1778000900))

        with pytest.raises(httpx.HTTPStatusError):
            self._run(monkeypatch, tmp_path, handler)

        out, err = capsys.readouterr()
        assert out == ""
        assert "X API usage: 2 call(s)" in err
        assert "rate limit users/:id/tweets: 0/1500 remaining" in err
