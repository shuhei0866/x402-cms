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
    ISSUES_COLLECTION,
    X_COLLECTION,
    CrossReference,
    DigestBundle,
    digest_has_content,
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


def _pr_kind_dict(
    number: int,
    *,
    kind: str,
    status: str,
    updated_at: datetime | None = None,
    created_at: datetime | None = None,
    week: str = "2026-W19",
) -> dict:
    """A non-merged PR document the multi-kind indexer writes."""
    return {
        "repo": "x402-foundation/x402",
        "pr_number": number,
        "title": f"PR {number}",
        "author": "someone",
        "url": f"https://github.com/x402-foundation/x402/pull/{number}",
        "week": week,
        "status": status,
        "kind": kind,
        "merged_at": None,
        "updated_at": updated_at.isoformat() if updated_at else None,
        "created_at": created_at.isoformat() if created_at else None,
        "comments": 3,
        "labels": [],
    }


def _issue_dict(
    number: int,
    *,
    comments: int = 5,
    updated_at: datetime | None = None,
    week: str = "2026-W19",
) -> dict:
    """An active issue document from the `issues` collection."""
    return {
        "repo": "x402-foundation/x402",
        "issue_number": number,
        "title": f"Issue {number}",
        "author": "someone",
        "url": f"https://github.com/x402-foundation/x402/issues/{number}",
        "week": week,
        "state": "open",
        "kind": "active",
        "comments": comments,
        "created_at": None,
        "updated_at": updated_at.isoformat() if updated_at else None,
        "closed_at": None,
        "labels": [],
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
    issue_payloads: list[dict] | None = None,
) -> MagicMock:
    """A MagicMock firestore client whose `.collection(name)` routes to
    the right docs depending on which collection the reader queries.
    `load_digest_bundle` reads `source_data` three times (merged /
    active / new) and four collections in all, so every `.stream()`
    hands back a fresh iterator and `issues` is routed too. Commentary
    and issues default to empty so the existing PR / X assertions stay
    focused."""
    client = MagicMock()

    def _coll(payloads: list[dict]) -> MagicMock:
        coll = MagicMock()
        coll.where.return_value.stream.side_effect = lambda *a, **k: iter(
            _docs(payloads)
        )
        return coll

    pr_coll = _coll(pr_payloads)
    x_coll = _coll(x_post_payloads)
    c_coll = _coll(commentary_payloads or [])
    i_coll = _coll(issue_payloads or [])

    def route(name: str) -> MagicMock:
        if name == COLLECTION:
            return pr_coll
        if name == X_COLLECTION:
            return x_coll
        if name == COMMENTARY_COLLECTION:
            return c_coll
        if name == ISSUES_COLLECTION:
            return i_coll
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
        # Phase 3: handle_clusters defaults to an empty dict so older
        # call sites (no curated mapping) keep working.
        assert bundle.handle_clusters == {}

    def test_handle_clusters_is_carried_through(self) -> None:
        bundle = DigestBundle(
            week="2026-W19",
            repo="x402-foundation/x402",
            prs=[],
            x_posts=[],
            cross_references=[],
            handle_clusters={"0x_natto": "japan"},
        )
        assert bundle.handle_clusters == {"0x_natto": "japan"}

    def test_content_detection_covers_every_rendered_collection(self) -> None:
        content_fields = (
            "prs",
            "active_prs",
            "new_prs",
            "issues",
            "x_posts",
            "commentaries",
        )
        for field_name in content_fields:
            bundle = DigestBundle(
                week="2026-W19",
                repo="x402-foundation/x402",
                prs=[],
                x_posts=[],
                cross_references=[],
            )
            assert digest_has_content(bundle) is False
            setattr(bundle, field_name, [object()])
            assert digest_has_content(bundle) is True


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

    def test_handle_clusters_passed_through_load(self) -> None:
        client = _client_with_two_collections([], [])
        clusters = {"0x_natto": "japan", "winor30": "japan"}
        bundle = load_digest_bundle(
            "2026-W19",
            repo="x402-foundation/x402",
            client=client,
            handle_clusters=clusters,
        )
        assert bundle.handle_clusters == clusters

    def test_no_handle_clusters_means_empty_dict(self) -> None:
        client = _client_with_two_collections([], [])
        bundle = load_digest_bundle(
            "2026-W19",
            repo="x402-foundation/x402",
            client=client,
        )
        assert bundle.handle_clusters == {}

    def test_separates_prs_by_kind_and_loads_issues(self) -> None:
        # `source_data` mixes merged / active / new rows under `kind`;
        # the bundle routes each to its own list, and `issues` comes
        # from the separate collection. read_week keeps merged (and
        # kind-less) rows; the active / new readers each keep their own
        # kind. Issues sort most-discussed first.
        pr_payloads = [
            _pr_dict(1, merged_at=datetime(2026, 5, 5, tzinfo=timezone.utc)),
            _pr_kind_dict(
                2,
                kind="active",
                status="open",
                updated_at=datetime(2026, 5, 7, tzinfo=timezone.utc),
            ),
            _pr_kind_dict(
                3,
                kind="new",
                status="open",
                created_at=datetime(2026, 5, 6, tzinfo=timezone.utc),
            ),
        ]
        issue_payloads = [_issue_dict(10, comments=8), _issue_dict(11, comments=2)]
        client = _client_with_two_collections(
            pr_payloads, [], issue_payloads=issue_payloads
        )

        bundle = load_digest_bundle(
            "2026-W19", repo="x402-foundation/x402", client=client
        )

        assert [pr.pr_number for pr in bundle.prs] == [1]
        assert [pr.pr_number for pr in bundle.active_prs] == [2]
        assert [pr.pr_number for pr in bundle.new_prs] == [3]
        assert bundle.active_prs[0].kind == "active"
        assert bundle.new_prs[0].kind == "new"
        assert [i.issue_number for i in bundle.issues] == [10, 11]
