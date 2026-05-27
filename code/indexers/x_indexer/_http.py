"""X API client and tweet → `XPost` normaliser.

Two narrow callables over `httpx`:
- `resolve_handle_to_id` — `@handle` → numeric id, classifying the
  200+errors quirk where X reports unknown handle.
- `fetch_user_tweets` — paginated timeline fetch with retweets
  excluded, results normalised to `XPost` with t.co URLs already
  expanded so the cross-reference parser sees real GitHub URLs.

`_to_xpost` lives here, not in the schema module: expanding
`entities.urls` is API-specific knowledge that the schema should not
need to carry.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import httpx

from code.indexers.x_text_parser import parse_pr_references
from code.schemas.x_post import XPost, XPostMetrics
from code.utils.dates import week_of

X_API_BASE = os.getenv("X_API_BASE", "https://api.x.com")

# Fields the indexer reads back out of each tweet row. Lock the set
# here so the response shape and `_to_xpost` stay in sync.
# `entities` carries the expanded form of every t.co URL so we can
# rewrite text before parsing PR references.
TWEET_FIELDS = "created_at,public_metrics,conversation_id,referenced_tweets,entities"
PAGE_SIZE = 100


class HandleNotFoundError(LookupError):
    """Raised when the X user lookup endpoint reports unknown handle."""


def _normalise_handle(handle: str) -> str:
    return handle.lstrip("@").strip()


def _iso_z(dt: datetime) -> str:
    """ISO-8601 UTC with trailing `Z`, the literal form X API consumes."""
    if dt.tzinfo is None:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_handle_to_id(handle: str, *, client: httpx.Client, bearer: str) -> str:
    """Return the numeric X user id for a handle (no `@` prefix required).

    Single round-trip to `GET /2/users/by/username/{handle}`. The
    resolver does not retry: rate-limit and transport failures bubble
    out as `httpx.HTTPStatusError` / `httpx.HTTPError` so the
    orchestrator can decide backoff strategy.

    Quirk: X API returns user-not-found as `200` with an `errors`
    array (`type` ending in `resource-not-found`), not as a 404. The
    resolver classifies both as `HandleNotFoundError` so the
    orchestrator does not need to know which form the API used.
    """
    name = _normalise_handle(handle)
    response = client.get(
        f"{X_API_BASE}/2/users/by/username/{name}",
        headers={"Authorization": f"Bearer {bearer}"},
    )
    if response.status_code == 404:
        raise HandleNotFoundError(name)
    response.raise_for_status()
    payload = response.json()

    errors = payload.get("errors") or []
    if errors:
        first = errors[0]
        err_type = first.get("type") or ""
        if "resource-not-found" in err_type or first.get("title") == "Not Found Error":
            raise HandleNotFoundError(name)
        raise RuntimeError(f"X API error for handle '{name}': {first}")

    return str(payload["data"]["id"])


def _expand_tco_urls(text: str, entities: dict[str, Any] | None) -> str:
    """Replace every `t.co/...` short URL in `text` with its expansion.

    X returns the wrapped form in `text` and the canonical destination
    in `entities.urls[].expanded_url`. We swap them so downstream
    consumers (PR-reference parser, human-rendered digest) see the
    real target. Falls through unchanged if no entities are present.
    """
    if not entities:
        return text
    expanded = text
    for url in entities.get("urls") or []:
        short = url.get("url")
        canonical = url.get("expanded_url")
        if short and canonical:
            expanded = expanded.replace(short, canonical)
    return expanded


def _to_xpost(raw: dict[str, Any], *, user_id: str, handle: str) -> XPost:
    """Normalise a raw X API tweet row into an `XPost`.

    Pulls `in_reply_to_id` out of `referenced_tweets[type=replied_to].id`
    rather than the unrelated `in_reply_to_user_id` field that the API
    also surfaces. `referenced_prs` is populated at write time via the
    shared text parser, after t.co URLs have been expanded.
    """
    created_at = datetime.fromisoformat(raw["created_at"].replace("Z", "+00:00"))

    metrics: XPostMetrics | None = None
    pm = raw.get("public_metrics")
    if pm:
        metrics = XPostMetrics(**pm)

    in_reply_to_id: str | None = None
    for ref in raw.get("referenced_tweets") or []:
        if ref.get("type") == "replied_to":
            in_reply_to_id = str(ref.get("id")) if ref.get("id") is not None else None
            break

    text = _expand_tco_urls(raw["text"], raw.get("entities"))
    return XPost(
        post_id=str(raw["id"]),
        author_handle=handle,
        author_id=user_id,
        created_at=created_at,
        text=text,
        url=f"https://x.com/{handle}/status/{raw['id']}",
        week=week_of(created_at),
        in_reply_to_id=in_reply_to_id,
        conversation_id=str(raw["conversation_id"]) if raw.get("conversation_id") else None,
        referenced_prs=parse_pr_references(text),
        metrics=metrics,
    )


def fetch_user_tweets(
    user_id: str,
    handle: str,
    start: datetime,
    end: datetime,
    *,
    client: httpx.Client,
    bearer: str,
) -> list[XPost]:
    """Fetch tweets in `[start, end)` for one user, paginated to the end.

    Caller supplies the time window in UTC. Retweets are excluded; the
    page size is the API maximum (100) so the call count stays low.
    """
    handle_norm = _normalise_handle(handle)
    posts: list[XPost] = []
    pagination_token: str | None = None

    while True:
        params: dict[str, str] = {
            "start_time": _iso_z(start),
            "end_time": _iso_z(end),
            "max_results": str(PAGE_SIZE),
            "exclude": "retweets",
            "tweet.fields": TWEET_FIELDS,
        }
        if pagination_token:
            params["pagination_token"] = pagination_token

        response = client.get(
            f"{X_API_BASE}/2/users/{user_id}/tweets",
            params=params,
            headers={"Authorization": f"Bearer {bearer}"},
        )
        response.raise_for_status()
        payload = response.json()

        for raw in payload.get("data") or []:
            posts.append(_to_xpost(raw, user_id=user_id, handle=handle_norm))

        meta = payload.get("meta") or {}
        pagination_token = meta.get("next_token")
        if not pagination_token:
            break

    return posts
