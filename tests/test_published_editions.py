"""Published edition index derived from live week-level commentary."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from code.renderers.digest import (
    COMMENTARY_COLLECTION,
    PublishedEdition,
    read_published_editions,
)


def _doc(
    slug: str,
    week: str,
    title: str,
    published_at: datetime,
) -> MagicMock:
    doc = MagicMock()
    doc.to_dict.return_value = {
        "slug": slug,
        "week": week,
        "week_level": True,
        "target_refs": [],
        "title": title,
        "body_md": "body",
        "published": True,
        "published_at": published_at.isoformat(),
        "tags": [],
    }
    return doc


def test_reader_queries_live_week_level_commentary() -> None:
    client = MagicMock()
    client.collection.return_value.where.return_value.stream.return_value = iter([])

    read_published_editions(client=client)

    client.collection.assert_called_once_with(COMMENTARY_COLLECTION)
    client.collection.return_value.where.assert_called_once()
    assert "filter" in client.collection.return_value.where.call_args.kwargs


def test_reader_returns_newest_week_first() -> None:
    client = MagicMock()
    docs = [
        _doc(
            "w24",
            "2026-W24",
            "Earlier edition",
            datetime(2026, 6, 15, tzinfo=timezone.utc),
        ),
        _doc(
            "w28",
            "2026-W28",
            "Latest edition",
            datetime(2026, 7, 13, tzinfo=timezone.utc),
        ),
    ]
    client.collection.return_value.where.return_value.stream.return_value = iter(docs)

    editions = read_published_editions(client=client)

    assert [edition.week for edition in editions] == ["2026-W28", "2026-W24"]
    assert all(isinstance(edition, PublishedEdition) for edition in editions)
    assert editions[0].title == "Latest edition"


def test_reader_keeps_latest_duplicate_for_backward_compatibility() -> None:
    client = MagicMock()
    docs = [
        _doc(
            "old",
            "2026-W28",
            "Old title",
            datetime(2026, 7, 12, tzinfo=timezone.utc),
        ),
        _doc(
            "new",
            "2026-W28",
            "Current title",
            datetime(2026, 7, 13, tzinfo=timezone.utc),
        ),
    ]
    client.collection.return_value.where.return_value.stream.return_value = iter(docs)

    editions = read_published_editions(client=client)

    assert len(editions) == 1
    assert editions[0].title == "Current title"


def test_reader_tolerates_historical_naive_published_timestamp() -> None:
    client = MagicMock()
    docs = [
        _doc(
            "old",
            "2026-W28",
            "Old title",
            datetime(2026, 7, 12),
        ),
        _doc(
            "new",
            "2026-W28",
            "Current title",
            datetime(2026, 7, 13, tzinfo=timezone.utc),
        ),
    ]
    client.collection.return_value.where.return_value.stream.return_value = iter(docs)

    editions = read_published_editions(client=client)

    assert editions[0].title == "Current title"
