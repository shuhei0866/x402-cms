"""Tests for the commentary side of the renderer.

`read_commentary_for_week` mirrors the PR / X readers (filter by week,
rehydrate the typed model, sort). `DigestBundle` gains a
`commentaries` list. `derive_recommendations` is the renderer-side
filter that turns the commentary list into the ranked picks (the
design keeps recommendations as a derived view, not a separate
collection).
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from code.renderers.digest import (
    COLLECTION,
    COMMENTARY_COLLECTION,
    X_COLLECTION,
    DigestBundle,
    derive_recommendations,
    load_digest_bundle,
    read_commentary_for_week,
)
from code.schemas.commentary import Commentary


def _commentary_dict(
    slug: str,
    *,
    week: str = "2026-W19",
    published_at: datetime,
    rank: int | None = None,
    tldr: str | None = None,
    week_level: bool = False,
) -> dict:
    d = {
        "slug": slug,
        "week": week,
        "week_level": week_level,
        "target_refs": [] if week_level else ["pr:x402-foundation/x402#1944"],
        "title": f"title {slug}",
        "body_md": f"body {slug}",
        "published": True,
        "published_at": published_at.isoformat(),
        "tags": [],
        "recommended_rank": rank,
        "tldr": tldr,
    }
    return d


def _docs(payloads: list[dict]) -> list[MagicMock]:
    out = []
    for p in payloads:
        m = MagicMock()
        m.to_dict.return_value = p
        out.append(m)
    return out


def _client_returning(payloads: list[dict]) -> MagicMock:
    client = MagicMock()
    where_q = client.collection.return_value.where.return_value
    where_q.stream.return_value = iter(_docs(payloads))
    return client


class TestReadCommentaryForWeek:
    def test_targets_commentary_collection_filtered_by_week(self) -> None:
        client = _client_returning([])
        read_commentary_for_week("2026-W19", client=client)
        client.collection.assert_called_once_with(COMMENTARY_COLLECTION)
        coll = client.collection.return_value
        coll.where.assert_called_once()
        assert "filter" in coll.where.call_args.kwargs

    def test_rehydrates_into_commentary(self) -> None:
        client = _client_returning(
            [
                _commentary_dict(
                    "2026-W19-a",
                    published_at=datetime(2026, 5, 13, tzinfo=timezone.utc),
                )
            ]
        )
        out = read_commentary_for_week("2026-W19", client=client)
        assert len(out) == 1
        assert isinstance(out[0], Commentary)
        assert out[0].slug == "2026-W19-a"

    def test_sorted_newest_first_by_published_at(self) -> None:
        older = _commentary_dict(
            "old", published_at=datetime(2026, 5, 11, tzinfo=timezone.utc)
        )
        newer = _commentary_dict(
            "new", published_at=datetime(2026, 5, 14, tzinfo=timezone.utc)
        )
        client = _client_returning([older, newer])
        out = read_commentary_for_week("2026-W19", client=client)
        assert [c.slug for c in out] == ["new", "old"]

    def test_empty_week_returns_empty(self) -> None:
        client = _client_returning([])
        assert read_commentary_for_week("2026-W19", client=client) == []


class TestDeriveRecommendations:
    def _c(self, slug: str, rank: int | None) -> Commentary:
        return Commentary(
            slug=slug,
            week="2026-W19",
            target_refs=["pr:x402-foundation/x402#1944"],
            title=slug,
            body_md="b",
            published=True,
            recommended_rank=rank,
            tldr="t" if rank else None,
        )

    def test_empty_when_nothing_recommended(self) -> None:
        commentaries = [self._c("a", None), self._c("b", None)]
        assert derive_recommendations(commentaries) == []

    def test_filters_non_recommended_and_sorts_by_rank(self) -> None:
        commentaries = [
            self._c("third", 3),
            self._c("plain", None),
            self._c("first", 1),
            self._c("second", 2),
        ]
        picks = derive_recommendations(commentaries)
        assert [c.slug for c in picks] == ["first", "second", "third"]


class TestBundleCarriesCommentary:
    def test_digest_bundle_has_commentaries_field(self) -> None:
        bundle = DigestBundle(
            week="2026-W19",
            repo="x402-foundation/x402",
            prs=[],
            x_posts=[],
            cross_references=[],
            commentaries=[],
        )
        assert bundle.commentaries == []

    def test_load_digest_bundle_includes_commentary(self) -> None:
        # Route by collection name so one client drives all readers.
        pr_coll = MagicMock()
        pr_coll.where.return_value.stream.return_value = iter([])
        x_coll = MagicMock()
        x_coll.where.return_value.stream.return_value = iter([])
        c_coll = MagicMock()
        c_coll.where.return_value.stream.return_value = iter(
            _docs(
                [
                    _commentary_dict(
                        "2026-W19-preface",
                        published_at=datetime(2026, 5, 13, tzinfo=timezone.utc),
                        week_level=True,
                    )
                ]
            )
        )

        client = MagicMock()

        def route(name: str) -> MagicMock:
            return {
                COLLECTION: pr_coll,
                X_COLLECTION: x_coll,
                COMMENTARY_COLLECTION: c_coll,
            }[name]

        client.collection.side_effect = route

        bundle = load_digest_bundle(
            "2026-W19", repo="x402-foundation/x402", client=client
        )
        assert len(bundle.commentaries) == 1
        assert bundle.commentaries[0].slug == "2026-W19-preface"
        assert bundle.commentaries[0].week_level is True
