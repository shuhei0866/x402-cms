"""Tests for the X-posts side of the digest reader.

The X reader mirrors `read_week` (PR reader): one `.collection().where()
.stream()` chain against Firestore, with results rehydrated into the
typed Pydantic shape and sorted newest-first so the renderer never
re-sorts.

`client` is injectable for the same reason it is on the writer — the
tests pin the call shape against a MagicMock instead of touching a
live Firestore.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from code.renderers.digest import X_COLLECTION, read_x_posts_for_week
from code.schemas.x_post import XPost


def _xpost_dict(
    post_id: str,
    created_at: datetime,
    *,
    week: str = "2026-W19",
    author: str = "phdargen",
) -> dict:
    return {
        "post_id": post_id,
        "author_handle": author,
        "author_id": "111",
        "created_at": created_at.isoformat(),
        "text": f"post {post_id}",
        "url": f"https://x.com/{author}/status/{post_id}",
        "week": week,
        "referenced_prs": [],
    }


def _client_returning(docs_payloads: list[dict]) -> MagicMock:
    client = MagicMock()
    coll = client.collection.return_value
    where_q = coll.where.return_value
    mocked_docs = []
    for payload in docs_payloads:
        d = MagicMock()
        d.to_dict.return_value = payload
        mocked_docs.append(d)
    where_q.stream.return_value = iter(mocked_docs)
    return client


class TestReadXPostsForWeek:
    def test_filters_by_week_and_targets_x_posts_collection(self) -> None:
        client = _client_returning([])
        read_x_posts_for_week("2026-W19", client=client)

        client.collection.assert_called_once_with(X_COLLECTION)
        # The reader uses `firestore.FieldFilter("week", "==", week)`,
        # which lands on `.where(filter=...)`. We only need to confirm
        # the filter went through `where` with a `filter=` kwarg.
        coll = client.collection.return_value
        coll.where.assert_called_once()
        assert "filter" in coll.where.call_args.kwargs

    def test_rehydrates_documents_into_xpost(self) -> None:
        docs = [
            _xpost_dict(
                "100",
                datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc),
            ),
        ]
        client = _client_returning(docs)

        posts = read_x_posts_for_week("2026-W19", client=client)

        assert len(posts) == 1
        assert isinstance(posts[0], XPost)
        assert posts[0].post_id == "100"

    def test_results_sorted_newest_first_by_created_at(self) -> None:
        # Firestore returns documents in arbitrary order; the reader
        # commits to newest-first so renderers never have to re-sort.
        oldest = _xpost_dict("a", datetime(2026, 5, 4, 0, 0, tzinfo=timezone.utc))
        middle = _xpost_dict("b", datetime(2026, 5, 7, 0, 0, tzinfo=timezone.utc))
        newest = _xpost_dict("c", datetime(2026, 5, 10, 23, 59, tzinfo=timezone.utc))
        client = _client_returning([middle, oldest, newest])

        posts = read_x_posts_for_week("2026-W19", client=client)

        assert [p.post_id for p in posts] == ["c", "b", "a"]

    def test_empty_week_returns_empty_list(self) -> None:
        client = _client_returning([])
        assert read_x_posts_for_week("2026-W19", client=client) == []
