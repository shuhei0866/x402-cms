"""Firestore readers for a single ISO week.

Three readers, one per source collection. Each filters by `week`,
rehydrates into the typed Pydantic model, and sorts newest-first so
the renderer never re-sorts.
"""

from __future__ import annotations

from datetime import datetime, timezone

from google.cloud import firestore

from code.schemas.commentary import Commentary
from code.schemas.pr import MergedPR
from code.schemas.x_post import XPost
from code.utils.firestore import build_client

COLLECTION = "source_data"
X_COLLECTION = "x_posts"
COMMENTARY_COLLECTION = "commentary"
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
    """
    fs = build_client(client, project)
    docs = (
        fs.collection(COLLECTION)
        .where(filter=firestore.FieldFilter("week", "==", week))
        .stream()
    )
    prs = [MergedPR.model_validate(doc.to_dict()) for doc in docs]
    prs.sort(key=lambda p: p.merged_at, reverse=True)
    return prs


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
