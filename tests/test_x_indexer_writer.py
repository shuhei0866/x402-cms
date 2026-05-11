"""Tests for `write_to_firestore` in the X indexer.

The writer is the boundary where the in-memory `XPost` row lands in
Firestore. We test the contract — collection name, document id,
serialisation mode, return value — by injecting a MagicMock client
and inspecting what `.collection(...).document(...).set(...)` saw.

We deliberately do not exercise google-cloud-firestore itself: that
SDK has its own tests, and the indexer is decoupled from its real
behaviour through a client parameter.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from code.indexers.x_indexer import X_COLLECTION, write_to_firestore
from code.schemas.x_post import XPost, XPostMetrics


def _post(post_id: str, *, week: str = "2026-W19") -> XPost:
    return XPost(
        post_id=post_id,
        author_handle="phdargen",
        author_id="111",
        created_at=datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc),
        text="hello",
        url=f"https://x.com/phdargen/status/{post_id}",
        week=week,
        metrics=XPostMetrics(like_count=1),
    )


class TestWriteToFirestore:
    def test_writes_each_post_to_x_posts_collection(self) -> None:
        client = MagicMock()
        collection = client.collection.return_value
        posts = [_post("1"), _post("2")]

        written = write_to_firestore(posts, client=client)

        assert written == 2
        client.collection.assert_called_once_with(X_COLLECTION)
        # The writer uses `collection.document(post_id).set(payload)`
        # twice — once per post.
        assert collection.document.call_count == 2
        document_calls = [call.args[0] for call in collection.document.call_args_list]
        assert document_calls == ["1", "2"]

    def test_uses_json_mode_dump_so_datetime_serialises_to_string(self) -> None:
        client = MagicMock()
        collection = client.collection.return_value
        post = _post("100")

        write_to_firestore([post], client=client)

        document = collection.document.return_value
        document.set.assert_called_once()
        payload = document.set.call_args.args[0]
        # In JSON mode the datetime becomes a string; in Python mode it
        # would still be a `datetime` object. Lock JSON mode.
        assert isinstance(payload["created_at"], str)
        assert payload["post_id"] == "100"
        assert payload["week"] == "2026-W19"
        assert payload["metrics"]["like_count"] == 1

    def test_empty_input_does_not_touch_collection(self) -> None:
        client = MagicMock()
        written = write_to_firestore([], client=client)
        assert written == 0
        # No `.collection().document(...).set(...)` calls because the
        # input list is empty; the collection accessor is allowed but
        # the document setter must not fire.
        collection = client.collection.return_value
        collection.document.assert_not_called()

    def test_x_collection_constant_is_separate_from_pr_collection(self) -> None:
        # Belt-and-suspenders: the renderer reads PRs and X posts from
        # disjoint collections, so this constant must not collide with
        # `github_indexer.COLLECTION` (which is "source_data").
        from code.indexers.github_indexer import COLLECTION as PR_COLLECTION

        assert X_COLLECTION != PR_COLLECTION
