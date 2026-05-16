"""Tests for the commentary additions to the agent JSON payload.

Two new top-level keys:
- `commentary`: the full Commentary rows (raw `body_md` included) — the
  agent buys the interpretation, so it gets the whole thing.
- `agent_recommendations`: lightweight slug references (slug + rank +
  tldr), ordered 1→2→3. The agent joins back to `commentary` by slug
  — same normalised pattern as `cross_references` (small payload even
  when the same note is both a pick and a body).

Pre-existing keys must stay intact so Phase-1/2 consumers don't break.
"""

from __future__ import annotations

import json

from code.renderers.digest import DigestBundle, render_agent_payload
from code.schemas.commentary import Commentary


def _c(slug: str, *, rank: int | None = None, week_level: bool = False) -> Commentary:
    return Commentary(
        slug=slug,
        week="2026-W19",
        week_level=week_level,
        target_refs=[] if week_level else ["pr:x402-foundation/x402#1944"],
        title=f"title {slug}",
        body_md=f"# {slug}\n\nbody markdown",
        published=True,
        recommended_rank=rank,
        tldr="one-liner" if rank else None,
    )


def _bundle(commentaries: list[Commentary]) -> DigestBundle:
    return DigestBundle(
        week="2026-W19",
        repo="x402-foundation/x402",
        prs=[],
        x_posts=[],
        cross_references=[],
        commentaries=commentaries,
    )


class TestAgentPayloadCommentary:
    def test_pre_existing_keys_still_present(self) -> None:
        payload = render_agent_payload(_bundle([]))
        for key in ("week", "repo", "count", "merged_prs", "x_posts", "cross_references"):
            assert key in payload

    def test_commentary_and_recommendations_keys_added(self) -> None:
        payload = render_agent_payload(_bundle([]))
        assert payload["commentary"] == []
        assert payload["agent_recommendations"] == []

    def test_commentary_carries_full_raw_body(self) -> None:
        payload = render_agent_payload(_bundle([_c("2026-W19-preface", week_level=True)]))
        assert len(payload["commentary"]) == 1
        row = payload["commentary"][0]
        assert row["slug"] == "2026-W19-preface"
        assert row["body_md"] == "# 2026-W19-preface\n\nbody markdown"
        assert row["week_level"] is True

    def test_agent_recommendations_are_slug_refs_ordered_by_rank(self) -> None:
        bundle = _bundle(
            [
                _c("third", rank=3),
                _c("plain"),
                _c("first", rank=1),
                _c("second", rank=2),
            ]
        )
        payload = render_agent_payload(bundle)

        assert payload["agent_recommendations"] == [
            {"slug": "first", "recommended_rank": 1, "tldr": "one-liner"},
            {"slug": "second", "recommended_rank": 2, "tldr": "one-liner"},
            {"slug": "third", "recommended_rank": 3, "tldr": "one-liner"},
        ]
        # All four commentaries (incl. the unranked one) are in the
        # full list; recommendations are the derived subset.
        assert len(payload["commentary"]) == 4

    def test_payload_round_trips_through_json(self) -> None:
        bundle = _bundle([_c("2026-W19-pick", rank=1)])
        payload = render_agent_payload(bundle)
        text = json.dumps(payload)
        assert "2026-W19-pick" in text
