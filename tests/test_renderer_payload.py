"""Tests for `render_agent_payload(bundle)`.

The agent JSON is the paid surface — once it's stable, consumers code
against its shape. We lock in the top-level keys, the normalised
join (cross_references carries `x_post_ids`, not inlined post bodies),
and JSON-mode datetime serialisation so the payload round-trips
through `json.dumps`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from code.renderers.digest import (
    CrossReference,
    DigestBundle,
    render_agent_payload,
)
from code.schemas.pr import MergedPR
from code.schemas.x_post import XPost


def _pr(number: int) -> MergedPR:
    return MergedPR(
        repo="x402-foundation/x402",
        pr_number=number,
        title=f"PR {number}",
        merged_at=datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc),
        author="someone",
        labels=[],
        url=f"https://github.com/x402-foundation/x402/pull/{number}",
        week="2026-W19",
    )


def _post(post_id: str, *, refs: list[str] | None = None) -> XPost:
    return XPost(
        post_id=post_id,
        author_handle="DukeOphir",
        author_id="111",
        created_at=datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc),
        text="builder thread",
        url=f"https://x.com/DukeOphir/status/{post_id}",
        week="2026-W19",
        referenced_prs=refs or [],
    )


def _bundle(prs=None, x_posts=None, cross_references=None) -> DigestBundle:
    return DigestBundle(
        week="2026-W19",
        repo="x402-foundation/x402",
        prs=prs or [],
        x_posts=x_posts or [],
        cross_references=cross_references or [],
    )


class TestRenderAgentPayload:
    def test_top_level_keys_present(self) -> None:
        payload = render_agent_payload(_bundle())
        # Phase 4 added `commentary` + `agent_recommendations`. The
        # set is pinned exactly so an accidental key add/rename is
        # caught — agents code against this shape.
        assert set(payload.keys()) == {
            "week",
            "repo",
            "count",
            "merged_prs",
            "x_posts",
            "cross_references",
            "commentary",
            "agent_recommendations",
        }

    def test_count_reflects_pr_total_only(self) -> None:
        # `count` is the PR count for backward compatibility with the
        # Phase 1 payload shape; X posts have their own length via
        # the list. Lock this so a future "total posts" rename does
        # not silently break agents.
        bundle = _bundle(prs=[_pr(1), _pr(2)], x_posts=[_post("a"), _post("b"), _post("c")])
        payload = render_agent_payload(bundle)
        assert payload["count"] == 2

    def test_merged_prs_serialise_via_json_mode(self) -> None:
        # JSON-mode dump turns datetimes into strings, which is what
        # `json.dumps` needs and what consumers expect to parse.
        bundle = _bundle(prs=[_pr(1944)])
        payload = render_agent_payload(bundle)
        assert isinstance(payload["merged_prs"][0]["merged_at"], str)
        assert payload["merged_prs"][0]["pr_number"] == 1944

    def test_x_posts_serialise_via_json_mode(self) -> None:
        bundle = _bundle(x_posts=[_post("100", refs=["x402-foundation/x402#1944"])])
        payload = render_agent_payload(bundle)
        assert isinstance(payload["x_posts"][0]["created_at"], str)
        assert payload["x_posts"][0]["post_id"] == "100"
        assert payload["x_posts"][0]["referenced_prs"] == ["x402-foundation/x402#1944"]

    def test_cross_references_are_normalised_ids_not_inlined_posts(self) -> None:
        # The whole point: cross_references is small (id refs only),
        # x_posts is the source of truth. Agent joins by id.
        bundle = _bundle(
            prs=[_pr(1944)],
            x_posts=[_post("100", refs=["x402-foundation/x402#1944"])],
            cross_references=[
                CrossReference(
                    pr_ref="x402-foundation/x402#1944",
                    x_post_ids=["100"],
                ),
            ],
        )
        payload = render_agent_payload(bundle)
        assert payload["cross_references"] == [
            {"pr_ref": "x402-foundation/x402#1944", "x_post_ids": ["100"]}
        ]

    def test_payload_round_trips_through_json_dumps(self) -> None:
        # End-to-end sanity: whatever is in the dict must be json
        # serialisable as-is. No leftover datetime / dataclass.
        bundle = _bundle(
            prs=[_pr(1944)],
            x_posts=[_post("100", refs=["x402-foundation/x402#1944"])],
            cross_references=[
                CrossReference("x402-foundation/x402#1944", ["100"]),
            ],
        )
        payload = render_agent_payload(bundle)
        # Must not raise.
        text = json.dumps(payload)
        assert "x402-foundation/x402#1944" in text
