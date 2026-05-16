"""Tests for the vault markdown parser.

A vault file is YAML frontmatter + a markdown body. The parser's job:
derive the slug from the filename (single source of truth — not a
frontmatter field that could drift), classify the publish action
(publish / unpublish / delete), and for a publish action build a
validated `Commentary` so a malformed note fails at parse time, not
at Firestore-write time.

Action classification:
- `delete: true`            → delete   (hard removal intent)
- `published: true`         → publish  (upsert)
- otherwise                 → unpublish (pull from serving, keep file)

For unpublish/delete only the slug matters, so the parser does not
require a fully valid Commentary — the file may be a gutted stub.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from code.publish.vault_parser import VaultParseError, parse_vault_file


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


class TestParseVaultFilePublish:
    def test_publish_file_builds_commentary_with_slug_from_filename(
        self, tmp_path: Path
    ) -> None:
        path = _write(
            tmp_path,
            "2026-W19-tvm-scheme.md",
            """---
week: 2026-W19
title: TVM scheme lands
published: true
target_refs:
  - pr:x402-foundation/x402#1944
tags:
  - python
  - sdk
---
The TVM exact-payment mechanism merged this week. Worth a look.
""",
        )
        result = parse_vault_file(path)

        assert result.action == "publish"
        assert result.slug == "2026-W19-tvm-scheme"
        c = result.commentary
        assert c is not None
        assert c.slug == "2026-W19-tvm-scheme"
        assert c.week == "2026-W19"
        assert c.title == "TVM scheme lands"
        assert c.target_refs == ["pr:x402-foundation/x402#1944"]
        assert c.tags == ["python", "sdk"]
        assert c.body_md.strip().startswith("The TVM exact-payment")
        assert c.published is True

    def test_recommended_commentary_parsed(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "2026-W19-pick.md",
            """---
week: 2026-W19
title: Pick of the week
published: true
target_refs:
  - pr:x402-foundation/x402#1944
recommended_rank: 1
tldr: TVM exact-payment is now in the Python SDK.
---
Body.
""",
        )
        result = parse_vault_file(path)
        assert result.commentary is not None
        assert result.commentary.recommended_rank == 1
        assert result.commentary.tldr == "TVM exact-payment is now in the Python SDK."

    def test_week_level_commentary_parsed(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "2026-W19-preface.md",
            """---
week: 2026-W19
title: This week in x402
published: true
week_level: true
---
A quiet but foundational week.
""",
        )
        result = parse_vault_file(path)
        assert result.action == "publish"
        assert result.commentary is not None
        assert result.commentary.week_level is True
        assert result.commentary.target_refs == []


class TestParseVaultFileActions:
    def test_published_false_is_unpublish(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "2026-W19-draft.md",
            """---
week: 2026-W19
title: Not ready
published: false
target_refs:
  - pr:x402-foundation/x402#1944
---
Still drafting.
""",
        )
        result = parse_vault_file(path)
        assert result.action == "unpublish"
        assert result.slug == "2026-W19-draft"
        # Non-publish actions only need the slug; we do not force a
        # valid Commentary so a half-written draft can still unpublish.
        assert result.commentary is None

    def test_missing_published_key_is_unpublish(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "2026-W19-wip.md",
            """---
week: 2026-W19
title: WIP
---
body
""",
        )
        result = parse_vault_file(path)
        assert result.action == "unpublish"

    def test_delete_true_is_delete_even_if_published(self, tmp_path: Path) -> None:
        # delete wins over published — explicit retraction intent.
        path = _write(
            tmp_path,
            "2026-W19-retract.md",
            """---
delete: true
published: true
---
""",
        )
        result = parse_vault_file(path)
        assert result.action == "delete"
        assert result.slug == "2026-W19-retract"
        assert result.commentary is None


class TestParseVaultFileErrors:
    def test_no_frontmatter_raises(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "x.md", "just a body, no frontmatter\n")
        with pytest.raises(VaultParseError):
            parse_vault_file(path)

    def test_unterminated_frontmatter_raises(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "x.md",
            "---\nweek: 2026-W19\ntitle: oops\n(no closing delimiter)\n",
        )
        with pytest.raises(VaultParseError):
            parse_vault_file(path)

    def test_invalid_commentary_propagates_on_publish(self, tmp_path: Path) -> None:
        # published:true but recommended_rank without tldr — the
        # Commentary validator must reject this at parse time.
        path = _write(
            tmp_path,
            "2026-W19-bad.md",
            """---
week: 2026-W19
title: Bad
published: true
target_refs:
  - pr:x402-foundation/x402#1944
recommended_rank: 2
---
no tldr
""",
        )
        with pytest.raises(VaultParseError):
            parse_vault_file(path)
