"""Publish the vault commentary directory to Firestore.

Scans `*.md`, classifies each file, validates across files, then
applies the actions. Validation is fail-fast and runs before any
write, so a `recommended_rank` collision within a week aborts the
whole run rather than leaving Firestore half-updated.

`unpublish` and `delete` both remove the Firestore document — the
serving layer only ever sees published commentary. The two actions
are kept distinct in the summary because the operator's intent
differs (temporarily pull vs. retract), which matters for the log.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from google.cloud import firestore

from code.publish.vault_parser import parse_vault_file

COMMENTARY_COLLECTION = "commentary"


class PublishError(Exception):
    """Raised when cross-file validation fails (e.g. duplicate rank)."""


def publish_vault_dir(
    vault_dir: Path | str,
    *,
    client: firestore.Client | None = None,
    project: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict:
    """Sync `vault_dir/*.md` to the Firestore `commentary` collection."""
    vault_dir = Path(vault_dir)
    now = now or datetime.now(timezone.utc)

    parsed = [parse_vault_file(p) for p in sorted(vault_dir.glob("*.md"))]

    # Cross-file invariant: within a week, recommended_rank is unique.
    # Checked before any write so a collision is atomic-fail.
    seen_ranks: dict[tuple[str, int], str] = {}
    for pf in parsed:
        if pf.action != "publish" or pf.commentary is None:
            continue
        rank = pf.commentary.recommended_rank
        if rank is None:
            continue
        key = (pf.commentary.week, rank)
        if key in seen_ranks:
            raise PublishError(
                f"duplicate recommended_rank {rank} in week "
                f"{pf.commentary.week}: '{seen_ranks[key]}' and "
                f"'{pf.commentary.slug}'"
            )
        seen_ranks[key] = pf.commentary.slug

    summary = {
        "published": 0,
        "unpublished": 0,
        "deleted": 0,
        "dry_run": dry_run,
    }

    if dry_run:
        for pf in parsed:
            summary[_summary_key(pf.action)] += 1
        return summary

    if not parsed:
        return summary

    fs = client or (
        firestore.Client(project=project) if project else firestore.Client()
    )
    collection = fs.collection(COMMENTARY_COLLECTION)

    for pf in parsed:
        doc = collection.document(pf.slug)
        if pf.action == "publish":
            assert pf.commentary is not None
            commentary = pf.commentary
            if commentary.published_at is None:
                commentary = commentary.model_copy(
                    update={"published_at": now}
                )
            doc.set(commentary.model_dump(mode="json"))
        else:
            # unpublish and delete both pull the doc from serving.
            doc.delete()
        summary[_summary_key(pf.action)] += 1

    return summary


def _summary_key(action: str) -> str:
    return {
        "publish": "published",
        "unpublish": "unpublished",
        "delete": "deleted",
    }[action]
