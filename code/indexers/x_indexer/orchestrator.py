"""Per-week orchestrator — resolve, fetch, optionally write.

Glues the network and storage halves of the package together. A
`HandleNotFoundError` on any handle is recorded and the run
continues, so one typo'd handle never erases the rest of the
week's signal.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from google.cloud import firestore

from code.indexers.x_indexer._http import (
    HandleNotFoundError,
    fetch_user_tweets,
    resolve_handle_to_id,
)
from code.indexers.x_indexer.writer import write_to_firestore
from code.schemas.x_post import XPost
from code.utils.dates import parse_iso_week


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
