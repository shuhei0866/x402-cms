"""Tests for the `Commentary` schema.

Commentary is Shuhei's interpretation layer: it sits in the vault as
markdown, gets published to Firestore, and is read back by the
renderer. The model pins the invariants the publish path and the
renderer both rely on:

- a recommended commentary must carry a short tldr (the agent-facing
  one-liner) and that tldr is length-bounded;
- a week-level commentary is the week preface — it targets the whole
  week, so it must NOT also list per-item targets;
- a non-week commentary must target something, otherwise it would be
  an orphan with nowhere to render;
- target refs are typed tokens (`pr:` / `x:`) so the renderer join is
  unambiguous.

`week_level` is an explicit bool (not "empty target_refs means
week-level") so a forgotten ref cannot silently turn a per-item note
into a week preface.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from code.schemas.commentary import Commentary


def _commentary(**overrides) -> Commentary:
    base = dict(
        slug="2026-W19-batch-settlement",
        week="2026-W19",
        week_level=False,
        target_refs=["pr:x402-foundation/x402#1944"],
        title="TVM scheme lands",
        body_md="The TVM exact-payment mechanism merged this week.",
        published=True,
    )
    base.update(overrides)
    return Commentary(**base)


class TestCommentaryBasics:
    def test_minimal_per_target_commentary(self) -> None:
        c = _commentary()
        assert c.slug == "2026-W19-batch-settlement"
        assert c.week_level is False
        assert c.recommended_rank is None
        assert c.tldr is None
        assert c.tags == []
        assert c.published_at is None

    def test_week_level_commentary_has_no_targets(self) -> None:
        c = _commentary(week_level=True, target_refs=[])
        assert c.week_level is True
        assert c.target_refs == []

    def test_defaults_are_independent_lists(self) -> None:
        a = _commentary()
        b = _commentary()
        a.tags.append("spec")
        assert b.tags == []

    def test_json_round_trip(self) -> None:
        original = _commentary(
            recommended_rank=1,
            tldr="TVM exact-payment is now in the Python SDK.",
            tags=["python", "sdk"],
            published_at=datetime(2026, 5, 13, 9, 0, tzinfo=timezone.utc),
        )
        payload = original.model_dump(mode="json")
        assert isinstance(payload["published_at"], str)
        assert Commentary.model_validate(payload) == original


class TestRecommendationInvariants:
    def test_rank_requires_tldr(self) -> None:
        with pytest.raises(ValidationError):
            _commentary(recommended_rank=2, tldr=None)

    def test_rank_with_empty_tldr_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _commentary(recommended_rank=2, tldr="   ")

    def test_tldr_over_280_chars_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _commentary(recommended_rank=3, tldr="x" * 281)

    def test_tldr_exactly_280_ok(self) -> None:
        c = _commentary(recommended_rank=3, tldr="x" * 280)
        assert c.tldr is not None and len(c.tldr) == 280

    def test_rank_must_be_1_2_or_3(self) -> None:
        with pytest.raises(ValidationError):
            _commentary(recommended_rank=4, tldr="ok")

    def test_tldr_without_rank_is_allowed(self) -> None:
        # A tldr without a rank is harmless (just an unused summary);
        # only the reverse (rank without tldr) breaks the agent view.
        c = _commentary(tldr="a stray summary")
        assert c.recommended_rank is None
        assert c.tldr == "a stray summary"


class TestTargetInvariants:
    def test_non_week_level_requires_targets(self) -> None:
        with pytest.raises(ValidationError):
            _commentary(week_level=False, target_refs=[])

    def test_week_level_must_not_have_targets(self) -> None:
        with pytest.raises(ValidationError):
            _commentary(
                week_level=True,
                target_refs=["pr:x402-foundation/x402#1944"],
            )

    def test_target_ref_must_be_pr_or_x_token(self) -> None:
        with pytest.raises(ValidationError):
            _commentary(target_refs=["github.com/x402-foundation/x402/pull/1944"])

    def test_multiple_typed_targets_allowed(self) -> None:
        c = _commentary(
            target_refs=[
                "pr:x402-foundation/x402#1944",
                "x:2053166929116881149",
            ]
        )
        assert len(c.target_refs) == 2
