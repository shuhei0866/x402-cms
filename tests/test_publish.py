"""Tests for the publish path: vault dir -> Firestore `commentary`.

Contract:
- scan `*.md`, classify each (publish / unpublish / delete);
- validate cross-file before any write: within a week the
  `recommended_rank` values must be unique, and a collision fails the
  whole run (no partial Firestore state);
- publish stamps `published_at` at write time if the file did not pin
  one, so the timestamp reflects when it actually went live;
- unpublish and delete both remove the Firestore doc (the semantic
  difference is operator intent, surfaced in the summary counts);
- dry-run touches nothing and still reports what would happen.

Firestore is a MagicMock; we assert on `.collection().document().set/
delete` rather than exercising the real SDK.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from code.publish.publisher import (
    COMMENTARY_COLLECTION,
    PublishError,
    publish_vault_dir,
)

NOW = datetime(2026, 5, 16, 9, 0, tzinfo=timezone.utc)


def _write(d: Path, name: str, content: str) -> None:
    (d / name).write_text(content, encoding="utf-8")


def _publish_md(
    *,
    week: str = "2026-W19",
    title: str = "Note",
    rank: int | None = None,
    tldr: str | None = None,
    published_at: str | None = None,
) -> str:
    lines = [
        "---",
        f"week: {week}",
        f"title: {title}",
        "published: true",
        "target_refs:",
        "  - pr:x402-foundation/x402#1944",
    ]
    if rank is not None:
        lines.append(f"recommended_rank: {rank}")
    if tldr is not None:
        lines.append(f"tldr: {tldr}")
    if published_at is not None:
        lines.append(f"published_at: {published_at}")
    lines += ["---", "body text", ""]
    return "\n".join(lines)


class TestPublishHappyPath:
    def test_empty_dir_is_a_noop_summary(self, tmp_path: Path) -> None:
        client = MagicMock()
        result = publish_vault_dir(tmp_path, client=client, now=NOW)
        assert result["published"] == 0
        assert result["unpublished"] == 0
        assert result["deleted"] == 0
        client.collection.assert_not_called()

    def test_publish_upserts_and_stamps_published_at(self, tmp_path: Path) -> None:
        _write(tmp_path, "2026-W19-a.md", _publish_md())
        client = MagicMock()
        collection = client.collection.return_value

        result = publish_vault_dir(tmp_path, client=client, now=NOW)

        assert result["published"] == 1
        client.collection.assert_called_with(COMMENTARY_COLLECTION)
        collection.document.assert_called_with("2026-W19-a")
        payload = collection.document.return_value.set.call_args.args[0]
        # published_at was not pinned in the file → stamped with `now`.
        # Compare parsed instants, not the string form: pydantic emits
        # the RFC-3339 `Z` suffix while datetime.isoformat() emits
        # `+00:00`; both denote the same instant.
        assert datetime.fromisoformat(payload["published_at"]) == NOW
        assert payload["slug"] == "2026-W19-a"

    def test_pinned_published_at_is_preserved(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "2026-W19-b.md",
            _publish_md(published_at="2026-05-13T00:00:00+00:00"),
        )
        client = MagicMock()
        collection = client.collection.return_value

        publish_vault_dir(tmp_path, client=client, now=NOW)

        payload = collection.document.return_value.set.call_args.args[0]
        assert datetime.fromisoformat(payload["published_at"]) == datetime(
            2026, 5, 13, 0, 0, tzinfo=timezone.utc
        )

    def test_unpublish_deletes_doc(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "2026-W19-draft.md",
            "---\nweek: 2026-W19\ntitle: x\npublished: false\n---\nbody\n",
        )
        client = MagicMock()
        collection = client.collection.return_value

        result = publish_vault_dir(tmp_path, client=client, now=NOW)

        assert result["unpublished"] == 1
        collection.document.assert_called_with("2026-W19-draft")
        collection.document.return_value.delete.assert_called_once()

    def test_delete_removes_doc(self, tmp_path: Path) -> None:
        _write(tmp_path, "2026-W19-retract.md", "---\ndelete: true\n---\n")
        client = MagicMock()
        collection = client.collection.return_value

        result = publish_vault_dir(tmp_path, client=client, now=NOW)

        assert result["deleted"] == 1
        collection.document.return_value.delete.assert_called_once()

    def test_mixed_dir_counts(self, tmp_path: Path) -> None:
        _write(tmp_path, "2026-W19-p.md", _publish_md(title="P"))
        _write(
            tmp_path,
            "2026-W19-u.md",
            "---\nweek: 2026-W19\ntitle: U\npublished: false\n---\nb\n",
        )
        _write(tmp_path, "2026-W19-d.md", "---\ndelete: true\n---\n")
        client = MagicMock()

        result = publish_vault_dir(tmp_path, client=client, now=NOW)

        assert result["published"] == 1
        assert result["unpublished"] == 1
        assert result["deleted"] == 1


class TestRankUniqueness:
    def test_duplicate_rank_same_week_fails_before_any_write(
        self, tmp_path: Path
    ) -> None:
        _write(
            tmp_path,
            "2026-W19-x.md",
            _publish_md(title="X", rank=1, tldr="first pick"),
        )
        _write(
            tmp_path,
            "2026-W19-y.md",
            _publish_md(title="Y", rank=1, tldr="also rank 1"),
        )
        client = MagicMock()

        with pytest.raises(PublishError):
            publish_vault_dir(tmp_path, client=client, now=NOW)

        # Fail-fast: no Firestore writes happened.
        client.collection.assert_not_called()

    def test_same_rank_different_weeks_is_ok(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "2026-W19-x.md",
            _publish_md(week="2026-W19", title="X", rank=1, tldr="w19 pick"),
        )
        _write(
            tmp_path,
            "2026-W20-y.md",
            _publish_md(week="2026-W20", title="Y", rank=1, tldr="w20 pick"),
        )
        client = MagicMock()

        result = publish_vault_dir(tmp_path, client=client, now=NOW)
        assert result["published"] == 2


class TestDryRun:
    def test_dry_run_reports_but_does_not_write(self, tmp_path: Path) -> None:
        _write(tmp_path, "2026-W19-a.md", _publish_md())
        _write(tmp_path, "2026-W19-d.md", "---\ndelete: true\n---\n")
        client = MagicMock()

        result = publish_vault_dir(
            tmp_path, client=client, now=NOW, dry_run=True
        )

        assert result["published"] == 1
        assert result["deleted"] == 1
        assert result["dry_run"] is True
        client.collection.assert_not_called()
