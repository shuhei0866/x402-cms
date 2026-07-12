"""Published editorial editions derived from week-level commentary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from google.cloud import firestore

from code.renderers.digest.readers import COMMENTARY_COLLECTION
from code.schemas.commentary import Commentary
from code.utils.dates import parse_iso_week
from code.utils.firestore import build_client


def _utc_timestamp(value: datetime | None) -> datetime:
    """Comparable UTC timestamp, including historical naive values."""
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class PublishedEdition:
    """The minimal publication index row for one editorial week."""

    week: str
    title: str
    published_at: datetime | None


def read_published_editions(
    project: str | None = None,
    *,
    client: firestore.Client | None = None,
) -> list[PublishedEdition]:
    """Return live week-level commentary as newest-first editions.

    The commentary collection contains published documents only. A
    week-level note therefore acts as the v0 publication record without
    introducing a second collection. The publisher rejects new duplicates;
    if historical duplicates exist, the most recently published one wins.
    """
    fs = build_client(client, project)
    docs = (
        fs.collection(COMMENTARY_COLLECTION)
        .where(filter=firestore.FieldFilter("week_level", "==", True))
        .stream()
    )
    by_week: dict[str, PublishedEdition] = {}
    for doc in docs:
        commentary = Commentary.model_validate(doc.to_dict())
        candidate = PublishedEdition(
            week=commentary.week,
            title=commentary.title,
            published_at=commentary.published_at,
        )
        current = by_week.get(candidate.week)
        if current is None or _utc_timestamp(candidate.published_at) > _utc_timestamp(
            current.published_at
        ):
            by_week[candidate.week] = candidate

    return sorted(
        by_week.values(),
        key=lambda edition: parse_iso_week(edition.week)[0],
        reverse=True,
    )
