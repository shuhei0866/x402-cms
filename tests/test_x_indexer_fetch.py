"""Tests for `fetch_user_tweets` — per-handle window fetcher.

What we lock in:

- The request goes to `/2/users/{id}/tweets` with the bearer in the
  Authorization header.
- The window is sent as ISO-8601 UTC strings with a trailing `Z`, the
  exact form the X API wants. `exclude=retweets` and `max_results=100`
  ride along to cap noise and per-call cost.
- `tweet.fields` advertises every field the indexer reads, so the
  response is not silently missing `created_at` / `public_metrics` /
  `conversation_id` / `referenced_tweets`.
- Pagination is consumed automatically until `next_token` disappears.
- The normalisation step pulls `in_reply_to_id` out of the
  `referenced_tweets` array (where `type == "replied_to"`), not the
  unrelated `in_reply_to_user_id` field that the API also surfaces.
- `referenced_prs` are populated from the tweet text via the shared
  parser, so the cross-reference primitive is set at write time.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from code.indexers.x_indexer import fetch_user_tweets

BEARER = "test-bearer"
START = datetime(2026, 5, 4, 0, 0, tzinfo=timezone.utc)
END = datetime(2026, 5, 11, 0, 0, tzinfo=timezone.utc)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


class TestFetchUserTweets:
    def test_single_tweet_is_normalised(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["params"] = dict(request.url.params)
            captured["auth"] = request.headers.get("authorization")
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "100",
                            "text": (
                                "shipped "
                                "https://github.com/x402-foundation/x402/pull/2199"
                            ),
                            "created_at": "2026-05-05T12:00:00.000Z",
                            "conversation_id": "100",
                            "public_metrics": {
                                "like_count": 5,
                                "retweet_count": 1,
                                "reply_count": 0,
                                "quote_count": 0,
                            },
                        },
                    ],
                    "meta": {"result_count": 1},
                },
            )

        with _client(handler) as client:
            posts = fetch_user_tweets(
                user_id="123",
                handle="phdargen",
                start=START,
                end=END,
                client=client,
                bearer=BEARER,
            )

        assert len(posts) == 1
        post = posts[0]
        assert post.post_id == "100"
        assert post.author_id == "123"
        assert post.author_handle == "phdargen"
        assert post.text.startswith("shipped ")
        assert post.referenced_prs == ["x402-foundation/x402#2199"]
        assert post.week == "2026-W19"
        assert post.url == "https://x.com/phdargen/status/100"
        assert post.conversation_id == "100"
        assert post.in_reply_to_id is None
        assert post.metrics is not None
        assert post.metrics.like_count == 5

        assert captured["auth"] == f"Bearer {BEARER}"
        assert "/2/users/123/tweets" in captured["url"]
        params = captured["params"]
        assert params["start_time"] == "2026-05-04T00:00:00Z"
        assert params["end_time"] == "2026-05-11T00:00:00Z"
        assert params["exclude"] == "retweets"
        assert params["max_results"] == "100"
        # tweet.fields lists everything the indexer reads back; if a
        # future change drops one of these, the test catches it.
        fields = params["tweet.fields"].split(",")
        for required in (
            "created_at",
            "public_metrics",
            "conversation_id",
            "referenced_tweets",
        ):
            assert required in fields

    def test_empty_window_returns_empty_list(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"meta": {"result_count": 0}})

        with _client(handler) as client:
            posts = fetch_user_tweets(
                user_id="1",
                handle="x",
                start=START,
                end=END,
                client=client,
                bearer=BEARER,
            )

        assert posts == []

    def test_pagination_follows_next_token(self) -> None:
        pagination_tokens_seen: list[str | None] = []

        def handler(request: httpx.Request) -> httpx.Response:
            token = request.url.params.get("pagination_token")
            pagination_tokens_seen.append(token)
            if token is None:
                return httpx.Response(
                    200,
                    json={
                        "data": [
                            {
                                "id": "1",
                                "text": "first",
                                "created_at": "2026-05-05T00:00:00.000Z",
                                "conversation_id": "1",
                            }
                        ],
                        "meta": {"result_count": 1, "next_token": "TOKEN_2"},
                    },
                )
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "2",
                            "text": "second",
                            "created_at": "2026-05-06T00:00:00.000Z",
                            "conversation_id": "2",
                        }
                    ],
                    "meta": {"result_count": 1},
                },
            )

        with _client(handler) as client:
            posts = fetch_user_tweets(
                user_id="1",
                handle="x",
                start=START,
                end=END,
                client=client,
                bearer=BEARER,
            )

        assert [p.post_id for p in posts] == ["1", "2"]
        assert pagination_tokens_seen == [None, "TOKEN_2"]

    def test_in_reply_to_id_from_referenced_tweets(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "200",
                            "text": "reply body",
                            "created_at": "2026-05-05T12:00:00.000Z",
                            "conversation_id": "150",
                            "referenced_tweets": [
                                {"type": "replied_to", "id": "150"},
                            ],
                        }
                    ],
                    "meta": {"result_count": 1},
                },
            )

        with _client(handler) as client:
            posts = fetch_user_tweets(
                user_id="1",
                handle="x",
                start=START,
                end=END,
                client=client,
                bearer=BEARER,
            )

        assert posts[0].in_reply_to_id == "150"
        assert posts[0].conversation_id == "150"

    def test_tco_urls_are_expanded_before_pr_reference_parsing(self) -> None:
        # X wraps every link in a t.co shortener and exposes the
        # canonical destination in `entities.urls[].expanded_url`. The
        # indexer must rewrite the text using those expansions before
        # `parse_pr_references` runs, otherwise PR links never appear
        # in `referenced_prs` and the join with GitHub source data is
        # silently empty.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "300",
                            "text": "shipped https://t.co/ABCDE today",
                            "created_at": "2026-05-05T12:00:00.000Z",
                            "conversation_id": "300",
                            "entities": {
                                "urls": [
                                    {
                                        "start": 8,
                                        "end": 28,
                                        "url": "https://t.co/ABCDE",
                                        "expanded_url": (
                                            "https://github.com/"
                                            "x402-foundation/x402/pull/2199"
                                        ),
                                        "display_url": (
                                            "github.com/x402-foundation/x402/pull/2199"
                                        ),
                                    }
                                ]
                            },
                        }
                    ],
                    "meta": {"result_count": 1},
                },
            )

        with _client(handler) as client:
            posts = fetch_user_tweets(
                user_id="1",
                handle="x",
                start=START,
                end=END,
                client=client,
                bearer=BEARER,
            )

        assert posts[0].referenced_prs == ["x402-foundation/x402#2199"]
        # The stored text shows the expanded URL too — the digest
        # renders the canonical destination, not the t.co shortener.
        assert "https://github.com/x402-foundation/x402/pull/2199" in posts[0].text
        assert "t.co/ABCDE" not in posts[0].text

    def test_entities_field_is_requested(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json={"meta": {"result_count": 0}})

        with _client(handler) as client:
            fetch_user_tweets(
                user_id="1",
                handle="x",
                start=START,
                end=END,
                client=client,
                bearer=BEARER,
            )

        fields = captured["params"]["tweet.fields"].split(",")
        assert "entities" in fields

    def test_missing_public_metrics_is_tolerated(self) -> None:
        # Under load X has been observed returning data rows without
        # public_metrics. The indexer must still emit the XPost row
        # with `metrics=None` so the rest of the digest is not blocked.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "1",
                            "text": "no metrics",
                            "created_at": "2026-05-05T00:00:00.000Z",
                            "conversation_id": "1",
                        }
                    ],
                    "meta": {"result_count": 1},
                },
            )

        with _client(handler) as client:
            posts = fetch_user_tweets(
                user_id="1",
                handle="x",
                start=START,
                end=END,
                client=client,
                bearer=BEARER,
            )

        assert posts[0].metrics is None
