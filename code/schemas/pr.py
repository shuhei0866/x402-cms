"""Pydantic schema for pull-request source data.

`PRRecord` is the canonical shape — it carries every PR the indexer
emits regardless of whether the PR is merged, still open, or freshly
opened during the week. `kind` records why the indexer picked the PR
up (which Search query matched it); `status` records the PR's own
state at index time.

`MergedPR` stays as a narrower view kept for the renderer/survey
path, which today only cares about merged rows. It is a subset of
`PRRecord` fields, so deserialising a merged PR document through
either class succeeds.

Two `PRRecord` fields exist only to feed the survey's scouting views
(`changed_paths` for the cross-SDK parity gap, `last_maintainer_activity_at`
for the stalled-PR list). The Search API does not carry either, so the
indexer fills them from a second pass over the per-PR REST endpoints;
both default to "unknown" so a row indexed before that pass — or one
whose enrichment the rate limiter cut short — still validates.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

PRStatus = Literal["merged", "open", "draft", "closed"]
PRKind = Literal["merged", "active", "new"]


class PRRecord(BaseModel):
    """A pull request from a tracked repository, in any state.

    Stored in the Firestore `source_data` collection with a document ID
    derived from `{repo_safe}_{pr_number}`, so multiple indexer kinds
    converging on the same PR upsert the same row. The `kind` field
    records which Search query surfaced the row most recently.
    """

    repo: str
    pr_number: int
    title: str
    author: str
    url: str
    week: str
    status: PRStatus
    kind: PRKind
    merged_at: datetime | None = None
    updated_at: datetime | None = None
    created_at: datetime | None = None
    comments: int = 0
    labels: list[str] = Field(default_factory=list)

    # --- enrichment pass (see module docstring) ---
    changed_paths: list[str] = Field(default_factory=list)
    """File paths the PR touches. Empty means "not indexed", not "none"."""

    paths_truncated: bool = False
    """True when the files endpoint was cut off at the page cap, so
    `changed_paths` is a prefix of the real list and an SDK the PR
    touches may be missing from it."""

    last_maintainer_activity_at: datetime | None = None
    """Newest review or comment from someone with write access to the
    repo, excluding the PR's own author and bots. `None` means no
    maintainer has reacted yet (or the row predates enrichment)."""

    maintainer_responders: list[str] = Field(default_factory=list)
    """Logins behind `last_maintainer_activity_at`, sorted."""


class MergedPR(BaseModel):
    """Merged-only view kept for the existing renderer/survey path.

    Field shape is a strict subset of `PRRecord`, so `model_validate`
    on a document the new indexer wrote will succeed as long as
    `merged_at` is populated (which it is for `kind=merged` rows).
    Readers that should only see merged rows filter on `kind==merged`
    or `status==merged` before deserialising into this class.
    """

    repo: str
    pr_number: int
    title: str
    merged_at: datetime
    author: str
    labels: list[str] = Field(default_factory=list)
    url: str
    week: str
