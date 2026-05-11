"""Tests for the `XPost` Firestore-bound schema.

The schema mirrors `MergedPR`: a Pydantic model that the indexer
produces and the renderer reads back from Firestore. The contract:
JSON-mode dump must round-trip back through `model_validate` so the
Firestore write path (`model_dump(mode='json')`) and the read path
(`model_validate` of `to_dict()` output) stay symmetric.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from code.schemas.x_post import XPost, XPostMetrics, week_of


def _fixture_post(**overrides) -> XPost:
    base = dict(
        post_id="1234567890",
        author_handle="phdargen",
        author_id="111222333",
        created_at=datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc),
        text="x402 builder thread",
        url="https://x.com/phdargen/status/1234567890",
        week="2026-W19",
    )
    base.update(overrides)
    return XPost(**base)


class TestXPost:
    def test_minimal_required_fields_validate(self) -> None:
        post = _fixture_post()
        assert post.post_id == "1234567890"
        assert post.author_handle == "phdargen"
        assert post.referenced_prs == []
        assert post.metrics is None
        assert post.conversation_id is None
        assert post.in_reply_to_id is None

    def test_missing_required_field_raises(self) -> None:
        with pytest.raises(ValidationError):
            XPost(  # type: ignore[call-arg]
                post_id="1",
                author_handle="x",
                # author_id missing
                created_at=datetime(2026, 5, 5, tzinfo=timezone.utc),
                text="hi",
                url="https://x.com/x/status/1",
                week="2026-W19",
            )

    def test_referenced_prs_default_is_independent_list(self) -> None:
        a = _fixture_post()
        b = _fixture_post()
        a.referenced_prs.append("x402-foundation/x402#100")
        assert b.referenced_prs == []

    def test_json_mode_round_trip(self) -> None:
        original = _fixture_post(
            referenced_prs=["x402-foundation/x402#2199"],
            conversation_id="999",
            in_reply_to_id="888",
            metrics=XPostMetrics(
                like_count=10,
                retweet_count=2,
                reply_count=1,
                quote_count=0,
            ),
        )
        payload = original.model_dump(mode="json")
        # JSON-mode dump must serialise datetimes as ISO strings, the
        # form Firestore stores (and what `to_dict()` returns on read).
        assert isinstance(payload["created_at"], str)
        rebuilt = XPost.model_validate(payload)
        assert rebuilt == original

    def test_url_is_not_validated_as_http_yet(self) -> None:
        # We accept the URL as a plain string for now; tighten if a
        # bug ever pushes a non-URL through. Keep the schema permissive
        # so the indexer never drops a tweet over URL parsing.
        post = _fixture_post(url="not a real url")
        assert post.url == "not a real url"


class TestXPostMetrics:
    def test_metrics_defaults_to_zero(self) -> None:
        m = XPostMetrics()
        assert m.like_count == 0
        assert m.retweet_count == 0
        assert m.reply_count == 0
        assert m.quote_count == 0

    def test_metrics_accepts_overrides(self) -> None:
        m = XPostMetrics(like_count=99)
        assert m.like_count == 99
        assert m.retweet_count == 0


class TestWeekOf:
    """`week_of` derives the ISO week label from a tweet `created_at`.

    The indexer uses it so the bucket on every post stays consistent
    with `previous_iso_week()` and the renderer's `read_week` index.
    """

    def test_monday_start(self) -> None:
        assert week_of(datetime(2026, 5, 4, 0, 0, tzinfo=timezone.utc)) == "2026-W19"

    def test_sunday_end(self) -> None:
        assert week_of(datetime(2026, 5, 10, 23, 59, tzinfo=timezone.utc)) == "2026-W19"

    def test_next_monday_rolls_over(self) -> None:
        assert week_of(datetime(2026, 5, 11, 0, 0, tzinfo=timezone.utc)) == "2026-W20"

    def test_year_boundary_iso_week_53(self) -> None:
        # 2026-01-01 is a Thursday — its ISO week is 2026-W01.
        # 2025-12-29 (Monday) is the start of 2026-W01 in ISO terms.
        assert week_of(datetime(2025, 12, 29, 0, 0, tzinfo=timezone.utc)) == "2026-W01"
