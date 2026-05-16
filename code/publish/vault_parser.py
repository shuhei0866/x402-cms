"""Parse a vault markdown file into a publish action + Commentary.

A vault file is YAML frontmatter delimited by `---` lines, followed by
a markdown body. The slug is the filename stem — a single source of
truth, so a renamed file is intentionally a new document rather than a
silent drift between filename and a frontmatter `slug:` field.

Action classification (delete wins, then published):
- `delete: true`    → delete    (explicit retraction)
- `published: true` → publish   (upsert a validated Commentary)
- otherwise         → unpublish (pull from serving, keep the file)

Only the publish action builds a `Commentary`, so a half-written
draft can still be unpublished/deleted without satisfying the full
schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from code.schemas.commentary import Commentary

Action = Literal["publish", "unpublish", "delete"]


class VaultParseError(Exception):
    """Raised when a vault file cannot be parsed into a publish action."""


@dataclass
class ParsedVaultFile:
    slug: str
    action: Action
    commentary: Commentary | None


def _split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        raise VaultParseError("missing frontmatter (file must start with '---')")

    lines = text.split("\n")
    closing_idx: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            closing_idx = i
            break
    if closing_idx is None:
        raise VaultParseError("unterminated frontmatter (no closing '---')")

    fm_text = "\n".join(lines[1:closing_idx])
    body = "\n".join(lines[closing_idx + 1 :])

    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as exc:
        raise VaultParseError(f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(fm, dict):
        raise VaultParseError("frontmatter must be a YAML mapping")
    return fm, body


def parse_vault_file(path: Path | str) -> ParsedVaultFile:
    """Read `path`, classify its action, and (for publish) validate it."""
    path = Path(path)
    slug = path.stem
    text = path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(text)

    if frontmatter.get("delete") is True:
        return ParsedVaultFile(slug=slug, action="delete", commentary=None)

    if frontmatter.get("published") is True:
        try:
            commentary = Commentary(
                slug=slug,
                week=frontmatter.get("week"),
                week_level=frontmatter.get("week_level", False),
                target_refs=frontmatter.get("target_refs") or [],
                title=frontmatter.get("title"),
                body_md=body.strip(),
                published=True,
                published_at=frontmatter.get("published_at"),
                tags=frontmatter.get("tags") or [],
                recommended_rank=frontmatter.get("recommended_rank"),
                tldr=frontmatter.get("tldr"),
            )
        except Exception as exc:  # pydantic ValidationError / coercion
            raise VaultParseError(
                f"invalid commentary in {path.name}: {exc}"
            ) from exc
        return ParsedVaultFile(slug=slug, action="publish", commentary=commentary)

    return ParsedVaultFile(slug=slug, action="unpublish", commentary=None)
