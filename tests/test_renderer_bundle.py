"""Tests for `DigestBundle` + `load_digest_bundle`.

The bundle is the renderer's input boundary: a single object that
carries everything a digest renders from. `load_digest_bundle` is the
narrow assembler that fans out to the two readers and the
cross-reference builder.

Tests use a MagicMock client that routes by collection name so we
can exercise both reader paths in one call without touching a real
Firestore.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from code.renderers.digest import (
    COLLECTION,
    COMMENTARY_COLLECTION,
    X_COLLECTION,
    CrossReference,
    DigestBundle,
    load_digest_bundle,
)


def _pr_dict(number: int, *, merged_at: datetime, week: str = "2026-W19") -> dict:
    return {
        "repo": "x402-foundation/x402",
        "pr_number": number,
        "title": f"PR {number}",
        "merged_at": merged_at.isoformat(),
        "author": "someone",
        "labels": [],
        "url": f"https://github.com/x402-foundation/x402/pull/{number}",
        "week": week,
    }


def _xpost_dict(
    post_id: str,
    *,
    created_at: datetime,
    refs: list[str] | None = None,
    week: str = "2026-W19",
) -> dict:
    return {
        "post_id": post_id,
        "author_handle": "phdargen",
        "author_id": "111",
        "created_at": created_at.isoformat(),
        "text": "post",
        "url": f"https://x.com/phdargen/status/{post_id}",
        "week": week,
        "referenced_prs": refs or [],
    }


def _docs(payloads: list[dict]) -> list[MagicMock]:
    out = []
    for p in payloads:
        d = MagicMock()
        d.to_dict.return_value = p
        out.append(d)
    return out


def _client_with_two_collections(
    pr_payloads: list[dict],
    x_post_payloads: list[dict],
    commentary_payloads: list[dict] | None = None,
) -> MagicMock:
    """A MagicMock firestore client whose `.collection(name)` routes to
    the right docs depending on which collection the reader queries.
    `load_digest_bundle` now reads three collections; commentary
    defaults to empty so the existing PR/X assertions stay focused."""
    client = MagicMock()

    pr_coll = MagicMock()
    pr_coll.where.return_value.stream.return_value = iter(_docs(pr_payloads))

    x_coll = MagicMock()
    x_coll.where.return_value.stream.return_value = iter(_docs(x_post_payloads))

    c_coll = MagicMock()
    c_coll.where.return_value.stream.return_value = iter(
        _docs(commentary_payloads or [])
    )

    def route(name: str) -> MagicMock:
        if name == COLLECTION:
            return pr_coll
        if name == X_COLLECTION:
            return x_coll
        if name == COMMENTARY_COLLECTION:
            return c_coll
        raise AssertionError(f"unexpected collection name: {name}")

    client.collection.side_effect = route
    return client


class TestDigestBundle:
    def test_dataclass_carries_all_five_fields(self) -> None:
        bundle = DigestBundle(
            week="2026-W19",
            repo="x402-foundation/x402",
            prs=[],
            x_posts=[],
            cross_references=[],
        )
        assert bundle.week == "2026-W19"
        assert bundle.repo == "x402-foundation/x402"
        assert bundle.prs == []
        assert bundle.x_posts == []
        assert bundle.cross_references == []


class TestLoadDigestBundle:
    def test_assembles_prs_x_posts_and_cross_references(self) -> None:
        pr_payloads = [
            _pr_dict(1944, merged_at=datetime(2026, 5, 5, 0, 0, tzinfo=timezone.utc)),
            _pr_dict(2199, merged_at=datetime(2026, 5, 8, 0, 0, tzinfo=timezone.utc)),
        ]
        x_post_payloads = [
            _xpost_dict(
                "tweet_1",
                created_at=datetime(2026, 5, 6, 0, 0, tzinfo=timezone.utc),
                refs=["x402-foundation/x402#1944"],
            ),
            _xpost_dict(
                "tweet_2",
                created_at=datetime(2026, 5, 7, 0, 0, tzinfo=timezone.utc),
                refs=[],
            ),
        ]
        client = _client_with_two_collections(pr_payloads, x_post_payloads)

        bundle = load_digest_bundle(
            "2026-W19",
            repo="x402-foundation/x402",
            client=client,
        )

        assert isinstance(bundle, DigestBundle)
        assert bundle.week == "2026-W19"
        assert bundle.repo == "x402-foundation/x402"
        assert [pr.pr_number for pr in bundle.prs] == [2199, 1944]  # newest first
        assert [p.post_id for p in bundle.x_posts] == ["tweet_2", "tweet_1"]
        assert len(bundle.cross_references) == 1
        cr = bundle.cross_references[0]
        assert isinstance(cr, CrossReference)
        assert cr.pr_ref == "x402-foundation/x402#1944"
        assert cr.x_post_ids == ["tweet_1"]

    def test_empty_collections_return_empty_bundle(self) -> None:
        client = _client_with_two_collections([], [])
        bundle = load_digest_bundle(
            "2026-W19",
            repo="x402-foundation/x402",
            client=client,
        )
        assert bundle.prs == []
        assert bundle.x_posts == []
        assert bundle.cross_references == []
