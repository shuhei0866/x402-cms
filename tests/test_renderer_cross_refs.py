"""Tests for `build_cross_references` — the PR ↔ X-post join.

The join is the load-bearing primitive Phase 2 was built for. We pin
down: which PRs are surfaced as keys, which posts are listed under
them, ordering within a key, and whether refs to PRs outside the
current week's PR set are dropped or kept.

`CrossReference` is a small dataclass — the test asserts on
`.pr_ref` / `.x_post_ids` rather than a dict shape.
"""

from __future__ import annotations

from datetime import datetime, timezone

from code.renderers.digest import CrossReference, build_cross_references
from code.schemas.pr import MergedPR
from code.schemas.x_post import XPost


def _pr(number: int, *, repo: str = "x402-foundation/x402") -> MergedPR:
    return MergedPR(
        repo=repo,
        pr_number=number,
        title=f"PR {number}",
        merged_at=datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc),
        author="someone",
        labels=[],
        url=f"https://github.com/{repo}/pull/{number}",
        week="2026-W19",
    )


def _post(
    post_id: str,
    *,
    refs: list[str] | None = None,
    created_at: datetime | None = None,
    handle: str = "phdargen",
) -> XPost:
    return XPost(
        post_id=post_id,
        author_handle=handle,
        author_id="111",
        created_at=created_at or datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc),
        text="post",
        url=f"https://x.com/{handle}/status/{post_id}",
        week="2026-W19",
        referenced_prs=refs or [],
    )


class TestBuildCrossReferences:
    def test_returns_empty_when_no_post_references_any_pr(self) -> None:
        prs = [_pr(1944), _pr(2199)]
        posts = [_post("p1"), _post("p2", refs=["other/repo#10"])]
        assert build_cross_references(prs, posts) == []

    def test_pairs_post_with_its_referenced_pr(self) -> None:
        prs = [_pr(1944), _pr(2199)]
        posts = [_post("p1", refs=["x402-foundation/x402#1944"])]

        result = build_cross_references(prs, posts)

        assert len(result) == 1
        assert isinstance(result[0], CrossReference)
        assert result[0].pr_ref == "x402-foundation/x402#1944"
        assert result[0].x_post_ids == ["p1"]

    def test_multiple_posts_under_same_pr_collected_in_post_order(self) -> None:
        # Posts come in newest-first (the reader's contract); the
        # cross-reference list preserves that order so the renderer
        # can show "most recently said" first.
        prs = [_pr(1944)]
        first = _post(
            "newer",
            refs=["x402-foundation/x402#1944"],
            created_at=datetime(2026, 5, 10, 0, 0, tzinfo=timezone.utc),
        )
        second = _post(
            "older",
            refs=["x402-foundation/x402#1944"],
            created_at=datetime(2026, 5, 4, 0, 0, tzinfo=timezone.utc),
        )
        result = build_cross_references(prs, [first, second])

        assert len(result) == 1
        assert result[0].x_post_ids == ["newer", "older"]

    def test_post_with_multiple_pr_refs_lands_under_each_pr(self) -> None:
        prs = [_pr(1944), _pr(2199)]
        posts = [
            _post(
                "p1",
                refs=["x402-foundation/x402#1944", "x402-foundation/x402#2199"],
            )
        ]
        result = build_cross_references(prs, posts)

        by_ref = {cr.pr_ref: cr for cr in result}
        assert by_ref["x402-foundation/x402#1944"].x_post_ids == ["p1"]
        assert by_ref["x402-foundation/x402#2199"].x_post_ids == ["p1"]

    def test_ref_to_pr_outside_current_pr_set_is_dropped(self) -> None:
        # MVP behaviour: only references that join to a PR present in
        # `prs` are surfaced. A tweet linking to last-week's PR (which
        # is not in this week's prs) is therefore silently dropped.
        # Renderer-side commentary can still see the raw reference in
        # the x_post's `referenced_prs`, but the cross-reference layer
        # is strictly join-only.
        prs = [_pr(1944)]
        posts = [_post("p1", refs=["x402-foundation/x402#9999"])]
        assert build_cross_references(prs, posts) == []

    def test_cross_reference_order_follows_pr_list_order(self) -> None:
        # The renderer iterates PR list newest-first; cross-refs in
        # the same order means the join section reads in the same
        # rhythm as the PR list above it.
        pr_old = _pr(1944)
        pr_old.merged_at = datetime(2026, 5, 4, 0, 0, tzinfo=timezone.utc)
        pr_new = _pr(2199)
        pr_new.merged_at = datetime(2026, 5, 10, 0, 0, tzinfo=timezone.utc)
        # Pass PRs in newest-first as the reader hands them out.
        prs = [pr_new, pr_old]
        posts = [
            _post("p1", refs=["x402-foundation/x402#1944"]),
            _post("p2", refs=["x402-foundation/x402#2199"]),
        ]
        result = build_cross_references(prs, posts)
        assert [cr.pr_ref for cr in result] == [
            "x402-foundation/x402#2199",
            "x402-foundation/x402#1944",
        ]
