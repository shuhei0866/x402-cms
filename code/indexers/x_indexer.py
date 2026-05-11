"""X (Twitter) indexer — fetch tweets from tracked handles.

Parallel to `github_indexer`. The indexer pulls tweets from a curated
list of handles (`config/tracked_handles.yaml`) for one ISO week and
writes them to the Firestore `x_posts` collection. The contract: every
network operation is a small pure-ish function that takes its
`httpx.Client` from the caller, so the orchestrator and the tests
share the same code path and the tests inject `MockTransport`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml
from google.cloud import firestore

from code.indexers.x_text_parser import parse_pr_references
from code.schemas.x_post import XPost, XPostMetrics
from code.utils.dates import parse_iso_week, previous_iso_week, week_of

X_API_BASE = os.getenv("X_API_BASE", "https://api.x.com")
X_COLLECTION = "x_posts"

# Fields the indexer reads back out of each tweet row. Lock the set
# here so the response shape and the normaliser stay in sync.
# `entities` carries the expanded form of every t.co URL so we can
# rewrite text before parsing PR references.
TWEET_FIELDS = "created_at,public_metrics,conversation_id,referenced_tweets,entities"
PAGE_SIZE = 100


class HandleNotFoundError(LookupError):
    """Raised when the X user lookup endpoint returns 404 for a handle."""


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


def write_to_firestore(
    posts: list[XPost],
    *,
    client: firestore.Client | None = None,
    project: str | None = None,
) -> int:
    """Upsert `XPost` rows into the `x_posts` Firestore collection.

    `client` is the injection seam used by tests; in production the
    orchestrator passes `None` and a real `firestore.Client` is built
    on demand. Doc id is the X post id directly — the post id is
    already a valid Firestore key.
    """
    if not posts:
        return 0
    fs = client or (
        firestore.Client(project=project) if project else firestore.Client()
    )
    collection = fs.collection(X_COLLECTION)
    for post in posts:
        collection.document(post.post_id).set(post.model_dump(mode="json"))
    return len(posts)


def load_tracked_handles(path: str | Path) -> list[str]:
    """Read a YAML list of handles, normalised (no `@`, non-empty entries).

    Format is a flat YAML list:

        - phdargen
        - CarsonRoscoe

    Blank entries are skipped, leading `@` is stripped. The file is
    expected to be private (`config/tracked_handles.yaml`, gitignored);
    the OSS surface ships `config/tracked_handles.example.yaml`.
    """
    with open(path, encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or []
    handles: list[str] = []
    for entry in raw:
        if entry is None:
            continue
        cleaned = str(entry).strip().lstrip("@").strip()
        if not cleaned:
            continue
        handles.append(cleaned)
    return handles


def run_for_week(
    week: str,
    handles: list[str],
    *,
    bearer: str,
    client: httpx.Client,
    fs_client: firestore.Client | None = None,
    project: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Resolve handles, fetch the week's tweets, optionally write.

    The week bounds come from `parse_iso_week`, the same helper the
    GitHub indexer uses, so the two pipelines align on Monday-Sunday
    bucketing. A `HandleNotFoundError` on any handle does not abort
    the run — the orchestrator records it and continues, so a typo'd
    handle does not erase the rest of the week's signal.
    """
    start_date, end_date = parse_iso_week(week)
    start_dt = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
    end_dt = datetime(end_date.year, end_date.month, end_date.day, tzinfo=timezone.utc)

    all_posts: list[XPost] = []
    failed_handles: list[str] = []
    processed = 0

    for handle in handles:
        try:
            user_id = resolve_handle_to_id(handle, client=client, bearer=bearer)
            posts = fetch_user_tweets(
                user_id=user_id,
                handle=handle,
                start=start_dt,
                end=end_dt,
                client=client,
                bearer=bearer,
            )
        except HandleNotFoundError:
            failed_handles.append(handle)
            continue
        all_posts.extend(posts)
        processed += 1

    posts_written = 0
    if not dry_run:
        posts_written = write_to_firestore(
            all_posts, client=fs_client, project=project
        )

    result: dict[str, Any] = {
        "week": week,
        "handles_processed": processed,
        "handles_failed": len(failed_handles),
        "failed_handles": failed_handles,
        "posts_fetched": len(all_posts),
        "posts_written": posts_written,
    }
    if dry_run:
        # Mirror github_indexer's dry-run: surface the actual rows so
        # `--dry-run` is a real preview, not just a count.
        result["posts"] = [p.model_dump(mode="json") for p in all_posts]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch tweets from tracked X handles into Firestore.",
    )
    parser.add_argument(
        "--week",
        default=None,
        help=(
            "ISO week label, e.g. '2026-W19'. Defaults to the ISO week "
            "of (today - 7 days), i.e. the previous week."
        ),
    )
    parser.add_argument(
        "--handles-config",
        default="config/tracked_handles.yaml",
        help="Path to the YAML file listing tracked handles.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and print results to stdout, but do not write to Firestore.",
    )
    args = parser.parse_args()

    bearer = os.getenv("X_BEARER_TOKEN")
    if not bearer:
        print(
            "X_BEARER_TOKEN is not set; export it via .env or env var "
            "before running the indexer.",
            file=sys.stderr,
        )
        return 2

    handles = load_tracked_handles(args.handles_config)
    if not handles:
        print(
            f"No handles found in {args.handles_config}; nothing to do.",
            file=sys.stderr,
        )
        return 0

    week = args.week or previous_iso_week()
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    print(
        f"Fetching tweets for {len(handles)} handle(s) over {week} "
        f"(project: {project or 'ADC default'}, dry_run={args.dry_run}).",
        file=sys.stderr,
    )

    with httpx.Client(timeout=30.0) as client:
        result = run_for_week(
            week=week,
            handles=handles,
            bearer=bearer,
            client=client,
            project=project,
            dry_run=args.dry_run,
        )

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
