"""Pydantic schema for Shuhei's commentary / interpretation layer.

A `Commentary` originates as a markdown file in the vault, is synced
to the Firestore `commentary` collection by the publish path, and is
read back by the renderer to dress the digest with interpretation.

Invariants live here (not in the publish script or the renderer) so
both ends trust the same shape:

- `recommended_rank` set ⇒ a non-empty, length-bounded `tldr` (the
  agent-facing one-liner the recommendation surfaces with);
- `week_level` commentary is the week preface — it covers the whole
  week, so it must not also enumerate per-item targets;
- a non-week commentary must target at least one item, else it would
  render nowhere;
- `target_refs` are typed tokens (`pr:` / `x:`) so the renderer's
  join against PRs / X posts is unambiguous.

`week_level` is an explicit bool rather than "empty target_refs means
week-level" so a forgotten ref cannot silently promote a per-item
note into the week preface.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

TLDR_MAX_CHARS = 280
TARGET_REF_PREFIXES = ("pr:", "x:")


class Commentary(BaseModel):
    """One interpretation note. Firestore doc id is `slug`."""

    slug: str
    week: str
    week_level: bool = False
    target_refs: list[str] = Field(default_factory=list)
    title: str
    body_md: str
    published: bool = False
    published_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    recommended_rank: Literal[1, 2, 3] | None = None
    tldr: str | None = None

    @model_validator(mode="after")
    def _check_invariants(self) -> Commentary:
        if self.recommended_rank is not None:
            if self.tldr is None or not self.tldr.strip():
                raise ValueError("recommended_rank requires a non-empty tldr")
            if len(self.tldr) > TLDR_MAX_CHARS:
                raise ValueError(f"tldr must be <= {TLDR_MAX_CHARS} chars")

        if self.week_level and self.target_refs:
            raise ValueError("week_level commentary must not list target_refs")

        if not self.week_level and not self.target_refs:
            raise ValueError(
                "non-week_level commentary must have at least one target_ref"
            )

        for ref in self.target_refs:
            if not ref.startswith(TARGET_REF_PREFIXES):
                raise ValueError(
                    f"target_ref {ref!r} must start with one of "
                    f"{TARGET_REF_PREFIXES}"
                )

        return self
