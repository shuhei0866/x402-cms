"""Pydantic schema for GitHub issue source data.

Issues are tracked separately from PRs because their lifecycle and
the signal we care about differ. PRs surface code review activity;
issues surface design discussion, RFC drafts, and bug reports — the
indexer picks them up when discussion is active (`comments >= N`)
rather than when they are merged.

Stored in the Firestore `issues` collection with a document ID derived
from `{repo_safe}_{issue_number}`, so the active-issue and (future)
merged-issue indexers upsert against the same row.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

IssueState = Literal["open", "closed"]


class IssueRecord(BaseModel):
    """An issue from a tracked repository within an ISO week.

    `kind=active` is the only kind written today (comments-based
    surfacing); leaving the field on the schema lets later indexers
    (e.g. `new` for freshly opened issues) coexist without a schema
    migration.
    """

    repo: str
    issue_number: int
    title: str
    author: str
    url: str
    week: str
    state: IssueState
    kind: Literal["active", "new"] = "active"
    comments: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    closed_at: datetime | None = None
    labels: list[str] = Field(default_factory=list)
