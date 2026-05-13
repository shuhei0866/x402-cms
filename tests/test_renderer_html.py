"""Tests for `render_html(bundle)`.

The HTML is still deliberately minimal — Phase 4's commentary layer
will dress it up. Phase 2's contract: the three sections (merged PRs,
X posts, cross-references) appear with their data, empty sections
render an explicit "no … this week" line so the page is never
silently truncated, and PR + X post fields are HTML-escaped.
"""

from __future__ import annotations

from datetime import datetime, timezone

from code.renderers.digest import CrossReference, DigestBundle, render_html
from code.schemas.pr import MergedPR
from code.schemas.x_post import XPost


def _pr(
    number: int,
    *,
    title: str = "feat: thing",
    author: str = "phdargen",
    repo: str = "x402-foundation/x402",
) -> MergedPR:
    return MergedPR(
        repo=repo,
        pr_number=number,
        title=title,
        merged_at=datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc),
        author=author,
        labels=[],
        url=f"https://github.com/{repo}/pull/{number}",
        week="2026-W19",
    )


def _post(post_id: str, *, text: str = "tweet", handle: str = "DukeOphir") -> XPost:
    return XPost(
        post_id=post_id,
        author_handle=handle,
        author_id="111",
        created_at=datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc),
        text=text,
        url=f"https://x.com/{handle}/status/{post_id}",
        week="2026-W19",
    )


def _bundle(
    *,
    prs: list[MergedPR] | None = None,
    x_posts: list[XPost] | None = None,
    cross_references: list[CrossReference] | None = None,
) -> DigestBundle:
    return DigestBundle(
        week="2026-W19",
        repo="x402-foundation/x402",
        prs=prs or [],
        x_posts=x_posts or [],
        cross_references=cross_references or [],
    )


class TestRenderHtml:
    def test_three_sections_present_in_output(self) -> None:
        # Empty bundle is enough to verify section presence.
        html = render_html(_bundle())
        assert "Merged PRs" in html
        assert "X posts" in html
        assert "Cross-references" in html

    def test_pr_item_carries_number_title_author(self) -> None:
        html = render_html(_bundle(prs=[_pr(1944, title="feat: TVM scheme", author="ArkadiyStena")]))
        assert "#1944" in html
        assert "feat: TVM scheme" in html
        assert "ArkadiyStena" in html

    def test_x_post_item_carries_handle_text_and_link(self) -> None:
        post = _post("12345", text="builder thread on x402", handle="DukeOphir")
        html = render_html(_bundle(x_posts=[post]))
        assert "DukeOphir" in html
        assert "builder thread on x402" in html
        assert "https://x.com/DukeOphir/status/12345" in html

    def test_cross_reference_item_carries_pr_ref_and_post_ids(self) -> None:
        bundle = _bundle(
            prs=[_pr(1944)],
            x_posts=[_post("12345")],
            cross_references=[
                CrossReference(pr_ref="x402-foundation/x402#1944", x_post_ids=["12345"]),
            ],
        )
        html = render_html(bundle)
        assert "x402-foundation/x402#1944" in html
        assert "12345" in html

    def test_empty_x_posts_renders_explicit_empty_message(self) -> None:
        html = render_html(_bundle(prs=[_pr(1)], x_posts=[], cross_references=[]))
        assert "No X posts" in html

    def test_empty_cross_references_renders_explicit_empty_message(self) -> None:
        html = render_html(_bundle(prs=[_pr(1)], x_posts=[_post("1")]))
        assert "No cross-references" in html

    def test_html_escapes_xss_payload_in_tweet_text(self) -> None:
        # X posts surface user-supplied text. Renderer must escape so
        # a tweet body cannot inject markup into the digest page.
        post = _post("100", text="<script>alert('xss')</script>")
        html = render_html(_bundle(x_posts=[post]))
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
