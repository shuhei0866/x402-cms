"""Pydantic schema for pull-request source data."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MergedPR(BaseModel):
    """A merged pull request from a tracked repository.

    Stored in the Firestore `source_data` collection with a document ID
    derived from `{repo_safe}_{pr_number}` so that re-running the indexer
    against the same window overwrites the existing document in place.
    """

    repo: str
    pr_number: int
    title: str
    merged_at: datetime
    author: str
    labels: list[str] = Field(default_factory=list)
    url: str
    week: str
