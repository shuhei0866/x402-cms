"""`x_posts` Firestore upserter.

Tests pass a MagicMock; production passes either nothing (ADC) or
the orchestrator's shared client so a single Firestore session
covers the whole week's batch.
"""

from __future__ import annotations

from google.cloud import firestore

from code.schemas.x_post import XPost
from code.utils.firestore import build_client

X_COLLECTION = "x_posts"


def write_to_firestore(
    posts: list[XPost],
    *,
    client: firestore.Client | None = None,
    project: str | None = None,
) -> int:
    """Upsert `XPost` rows into the `x_posts` Firestore collection.

    `client` is the injection seam used by tests; in production the
    orchestrator passes `None` and the shared `build_client` resolves
    to ADC. Doc id is the X post id directly — it is already a valid
    Firestore key.
    """
    if not posts:
        return 0
    collection = build_client(client, project).collection(X_COLLECTION)
    for post in posts:
        collection.document(post.post_id).set(post.model_dump(mode="json"))
    return len(posts)
