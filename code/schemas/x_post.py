"""Pydantic schema for X (Twitter) post source data.

Mirrors `MergedPR` in spirit: a flat Pydantic model the indexer
produces and the renderer reads back from Firestore. Stored in the
`x_posts` collection with the post id as the document key.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class XPostMetrics(BaseModel):
    """Engagement counters X exposes in `tweet.fields=public_metrics`.

    Defaulted to zero so the indexer can write a tweet whose metrics
    payload was missing (rare, but X API does return partial responses
    under load) without dropping the row.
    """

    like_count: int = 0
    retweet_count: int = 0
    reply_count: int = 0
    quote_count: int = 0


class XPost(BaseModel):
    """A tweet from a tracked X handle within an ISO week.

    `referenced_prs` carries `owner/repo#N` tokens extracted from the
    text, which is the cross-reference primitive used to join X posts
    to merged PRs at render time.
    """

    post_id: str
    author_handle: str
    author_id: str
    created_at: datetime
    text: str
    url: str
    week: str
    in_reply_to_id: str | None = None
    conversation_id: str | None = None
    referenced_prs: list[str] = Field(default_factory=list)
    metrics: XPostMetrics | None = None


def week_of(created_at: datetime) -> str:
    """Return the ISO week label (`YYYY-Www`) for a tweet's `created_at`.

    Pure on the input — no `today()` reference — so the bucket label
    stays stable when the indexer re-runs the same window.
    """
    iso_year, iso_week, _ = created_at.isocalendar()
    return f"{iso_year:04d}-W{iso_week:02d}"
