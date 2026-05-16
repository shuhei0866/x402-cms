"""Tests for commentary rendering in the human HTML view.

Rules locked here (from the 2026-05-16 design):
- week-level commentary → a preface section right after <h1>, before
  the data sections; absent entirely when there is no week note;
- recommended commentary → an ordered <ol> "Picks" section, rank 1→3;
- single-target commentary → an inline <blockquote> on that PR / X
  item;
- multi-target commentary → an end section, each with a stable
  `id="commentary-<slug>"` anchor;
- body markdown is converted to HTML and sanitised (a <script> in a
  body never reaches the page);
- the Phase-2 PR / X escaping still holds (regression).
"""

from __future__ import annotations

from datetime import datetime, timezone

from code.renderers.digest import DigestBundle, render_html
from code.schemas.commentary import Commentary
from code.schemas.pr import MergedPR
from code.schemas.x_post import XPost


def _pr(number: int, *, repo: str = "x402-foundation/x402") -> MergedPR:
    return MergedPR(
        repo=repo,
        pr_number=number,
        title=f"feat: thing {number}",
        merged_at=datetime(2026, 5, 13, tzinfo=timezone.utc),
        author="phdargen",
        labels=[],
        url=f"https://github.com/{repo}/pull/{number}",
        week="2026-W19",
    )


def _post(post_id: str) -> XPost:
    return XPost(
        post_id=post_id,
        author_handle="DukeOphir",
        author_id="1",
        created_at=datetime(2026, 5, 13, tzinfo=timezone.utc),
        text="a tweet",
        url=f"https://x.com/DukeOphir/status/{post_id}",
        week="2026-W19",
    )


def _c(
    slug: str,
    *,
    body_md: str = "plain body",
    week_level: bool = False,
    target_refs: list[str] | None = None,
    rank: int | None = None,
) -> Commentary:
    if week_level:
        refs: list[str] = []
    else:
        refs = target_refs if target_refs is not None else ["pr:x402-foundation/x402#1944"]
    return Commentary(
        slug=slug,
        week="2026-W19",
        week_level=week_level,
        target_refs=refs,
        title=f"title {slug}",
        body_md=body_md,
        published=True,
        recommended_rank=rank,
        tldr="the one-liner" if rank else None,
    )


def _bundle(
    *,
    prs: list[MergedPR] | None = None,
    x_posts: list[XPost] | None = None,
    commentaries: list[Commentary] | None = None,
) -> DigestBundle:
    return DigestBundle(
        week="2026-W19",
        repo="x402-foundation/x402",
        prs=prs or [],
        x_posts=x_posts or [],
        cross_references=[],
        commentaries=commentaries or [],
    )


class TestWeekPreface:
    def test_week_level_renders_preface_with_converted_markdown(self) -> None:
        c = _c("2026-W19-preface", week_level=True, body_md="A **foundational** week.")
        html = render_html(_bundle(commentaries=[c]))
        assert "<strong>foundational</strong>" in html
        # Preface comes before the Merged PRs section.
        assert html.index("foundational") < html.index("Merged PRs")

    def test_no_week_level_means_no_preface_marker(self) -> None:
        html = render_html(_bundle(prs=[_pr(1)]))
        assert "preface" not in html.lower()


class TestPicks:
    def test_recommended_render_as_ordered_list_by_rank(self) -> None:
        bundle = _bundle(
            commentaries=[
                _c("second", rank=2),
                _c("first", rank=1),
            ]
        )
        html = render_html(bundle)
        assert "<ol>" in html
        # rank 1 slug/title appears before rank 2 in the picks list.
        assert html.index("title first") < html.index("title second")
        assert "the one-liner" in html

    def test_no_recommendations_states_empty(self) -> None:
        html = render_html(_bundle(prs=[_pr(1)]))
        assert "No picks this week" in html


class TestInlineBlockquote:
    def test_single_target_commentary_blockquotes_on_its_pr(self) -> None:
        pr = _pr(1944)
        c = _c("note", target_refs=["pr:x402-foundation/x402#1944"], body_md="worth noting")
        html = render_html(_bundle(prs=[pr], commentaries=[c]))
        # `<blockquote id="commentary-…">` — match the open tag, not a
        # bare one; the id is the anchor a recommended pick links to.
        assert "<blockquote" in html
        assert 'id="commentary-note"' in html
        assert "worth noting" in html
        # the blockquote is near the PR it targets
        assert html.index("#1944") < html.index("worth noting")

    def test_single_target_commentary_blockquotes_on_its_x_post(self) -> None:
        post = _post("2053166929116881149")
        c = _c(
            "xnote",
            target_refs=["x:2053166929116881149"],
            body_md="tweet take",
        )
        html = render_html(_bundle(x_posts=[post], commentaries=[c]))
        assert "tweet take" in html


class TestMultiTargetSection:
    def test_multi_target_commentary_gets_anchored_end_section(self) -> None:
        c = _c(
            "cross-cut",
            target_refs=[
                "pr:x402-foundation/x402#1944",
                "x:2053166929116881149",
            ],
            body_md="connects the two",
        )
        html = render_html(_bundle(commentaries=[c]))
        assert 'id="commentary-cross-cut"' in html
        assert "connects the two" in html


class TestSanitisationAndRegression:
    def test_script_in_commentary_body_is_stripped(self) -> None:
        c = _c("xss", week_level=True, body_md="ok <script>alert(1)</script> done")
        html = render_html(_bundle(commentaries=[c]))
        # No script tag in any form reaches the page (escaped to an
        # inert entity by the md renderer, and nh3 as a second layer).
        assert "<script" not in html

    def test_pr_title_still_escaped(self) -> None:
        pr = _pr(1)
        pr.title = "<img src=x onerror=alert(1)>"
        html = render_html(_bundle(prs=[pr]))
        assert "<img src=x onerror=alert(1)>" not in html
        assert "&lt;img" in html

    def test_three_data_sections_still_present(self) -> None:
        html = render_html(_bundle(prs=[_pr(1)]))
        assert "Merged PRs" in html
        assert "X posts" in html
        assert "Cross-references" in html
