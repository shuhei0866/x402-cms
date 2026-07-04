"""Firestore readers for a single ISO week.

One reader per source signal. Each filters by `week`, rehydrates into
the typed Pydantic model, and sorts newest-first so the renderer never
re-sorts. `read_week` returns merged PRs; `read_prs_by_kind` returns
the active / new PRs the multi-kind indexer also writes to
`source_data`; `read_issues_for_week` reads the separate `issues`
collection.
"""

from __future__ import annotations

from datetime import datetime, timezone

from google.cloud import firestore

from code.schemas.commentary import Commentary
from code.schemas.issue import IssueRecord
from code.schemas.pr import MergedPR, PRRecord
from code.schemas.x_post import XPost
from code.utils.firestore import build_client

COLLECTION = "source_data"
X_COLLECTION = "x_posts"
COMMENTARY_COLLECTION = "commentary"
ISSUES_COLLECTION = "issues"
DEFAULT_REPO = "x402-foundation/x402"


def read_week(
    week: str,
    project: str | None = None,
    *,
    client: firestore.Client | None = None,
) -> list[MergedPR]:
    """Load merged PRs for a given ISO week from Firestore.

    Results are sorted newest-first on `merged_at` so both views render
    in chronological reverse order without each renderer having to
    re-sort.

    Skips non-merged rows that the active/new indexers may have written
    to the same collection. Pre-multi-kind documents lacked a `kind`
    field, so a missing `kind` is treated as merged for backward
    compatibility.
    """
    fs = build_client(client, project)
    docs = (
        fs.collection(COLLECTION)
        .where(filter=firestore.FieldFilter("week", "==", week))
        .stream()
    )
    prs: list[MergedPR] = []
    for doc in docs:
        data = doc.to_dict() or {}
        if data.get("kind", "merged") != "merged":
            continue
        prs.append(MergedPR.model_validate(data))
    prs.sort(key=lambda p: p.merged_at, reverse=True)
    return prs


def read_prs_by_kind(
    week: str,
    kind: str,
    project: str | None = None,
    *,
    client: firestore.Client | None = None,
) -> list[PRRecord]:
    """Load PRs of a given `kind` (``active`` / ``new``) for an ISO week.

    Reads the same `source_data` collection as `read_week`, but keeps
    the rows the multi-kind indexer labels `active` (open/draft PRs
    with live discussion) or `new` (opened this week). Those rows have
    no `merged_at`, so they rehydrate into `PRRecord` rather than the
    merged-only `MergedPR` view. Active rows sort most-discussed first
    (comment count, newest `updated_at` as tiebreak — the same rule as
    `read_issues_for_week`, so both discussion sections read hottest
    first). New rows sort newest-first on `created_at`. A min-sentinel
    keeps a missing timestamp at the bottom of its bucket.
    """
    fs = build_client(client, project)
    docs = (
        fs.collection(COLLECTION)
        .where(filter=firestore.FieldFilter("week", "==", week))
        .stream()
    )
    records: list[PRRecord] = []
    for doc in docs:
        data = doc.to_dict() or {}
        if data.get("kind") != kind:
            continue
        records.append(PRRecord.model_validate(data))
    _floor = datetime.min.replace(tzinfo=timezone.utc)
    if kind == "active":
        records.sort(
            key=lambda r: (r.comments, r.updated_at or _floor), reverse=True
        )
    else:
        records.sort(key=lambda r: r.created_at or _floor, reverse=True)
    return records


def read_x_posts_for_week(
    week: str,
    project: str | None = None,
    *,
    client: firestore.Client | None = None,
) -> list[XPost]:
    """Load X posts for a given ISO week from Firestore.

    Same shape as `read_week`: filter by `week`, rehydrate into the
    typed Pydantic model, sort newest-first on `created_at`. The
    renderer can then iterate without re-sorting.
    """
    fs = build_client(client, project)
    docs = (
        fs.collection(X_COLLECTION)
        .where(filter=firestore.FieldFilter("week", "==", week))
        .stream()
    )
    posts = [XPost.model_validate(doc.to_dict()) for doc in docs]
    posts.sort(key=lambda p: p.created_at, reverse=True)
    return posts


def read_commentary_for_week(
    week: str,
    project: str | None = None,
    *,
    client: firestore.Client | None = None,
) -> list[Commentary]:
    """Load commentary for a given ISO week from Firestore.

    Same shape as the other readers. The publish path only ever puts
    published commentary in the collection (unpublish/delete remove the
    doc), so everything read here is live. Sorted newest-first on
    `published_at`; a missing timestamp sorts last.
    """
    fs = build_client(client, project)
    docs = (
        fs.collection(COMMENTARY_COLLECTION)
        .where(filter=firestore.FieldFilter("week", "==", week))
        .stream()
    )
    commentaries = [Commentary.model_validate(doc.to_dict()) for doc in docs]
    # `published_at` is always stamped by the publish path, but guard a
    # missing one with a min-sentinel so the sort never compares None.
    _floor = datetime.min.replace(tzinfo=timezone.utc)
    commentaries.sort(
        key=lambda c: c.published_at or _floor,
        reverse=True,
    )
    return commentaries


def read_issues_for_week(
    week: str,
    project: str | None = None,
    *,
    client: firestore.Client | None = None,
) -> list[IssueRecord]:
    """Load active issues for a given ISO week from the `issues` collection.

    Issues live in their own collection (the issue indexer keeps them
    apart from PRs). Sorted most-discussed first — by comment count,
    then newest `updated_at` as a tiebreak — so the renderer surfaces
    the liveliest threads at the top. A missing `updated_at` sorts last
    within its comment-count bucket.
    """
    fs = build_client(client, project)
    docs = (
        fs.collection(ISSUES_COLLECTION)
        .where(filter=firestore.FieldFilter("week", "==", week))
        .stream()
    )
    issues = [IssueRecord.model_validate(doc.to_dict()) for doc in docs]
    _floor = datetime.min.replace(tzinfo=timezone.utc)
    issues.sort(key=lambda i: (i.comments, i.updated_at or _floor), reverse=True)
    return issues
