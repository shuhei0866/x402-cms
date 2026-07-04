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
from code.renderers.digest.topics import TopicRule, XKeywordRule
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


def _post(
    post_id: str,
    *,
    text: str = "tweet",
    handle: str = "DukeOphir",
    reply_to: str | None = None,
) -> XPost:
    return XPost(
        post_id=post_id,
        author_handle=handle,
        author_id="111",
        created_at=datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc),
        text=text,
        url=f"https://x.com/{handle}/status/{post_id}",
        week="2026-W19",
        in_reply_to_id=reply_to,
    )


def _bundle(
    *,
    prs: list[MergedPR] | None = None,
    x_posts: list[XPost] | None = None,
    cross_references: list[CrossReference] | None = None,
    topic_rules: list[TopicRule] | None = None,
    x_keywords: list[XKeywordRule] | None = None,
) -> DigestBundle:
    return DigestBundle(
        week="2026-W19",
        repo="x402-foundation/x402",
        prs=prs or [],
        x_posts=x_posts or [],
        cross_references=cross_references or [],
        topic_rules=topic_rules or [],
        x_keywords=x_keywords or [],
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

    def test_head_links_vendored_stylesheet_and_viewport(self) -> None:
        # The human view is styled by the vendored classless Pico
        # stylesheet; the markup itself stays class-free.
        html = render_html(_bundle())
        assert (
            '<link rel="stylesheet" href="/static/pico.classless.min.css">'
            in html
        )
        assert '<meta name="viewport"' in html

    def test_body_content_is_wrapped_in_main(self) -> None:
        # Pico's classless layout keys its container on `body > main`.
        html = render_html(_bundle())
        assert "<main>" in html
        assert "</main>" in html


class TestInformationDesign:
    """Snapshot line, section order, and the reply / closed folds."""

    def test_snapshot_line_summarises_the_week(self) -> None:
        html = render_html(
            _bundle(
                prs=[_pr(1)],
                x_posts=[_post("1"), _post("2", reply_to="1")],
            )
        )
        assert (
            "1 merged · 0 active discussions · 0 newly opened · "
            "0 issues · 1 X posts + 1 replies"
        ) in html

    def test_discussion_sections_come_before_merged(self) -> None:
        # Inverted pyramid: the hottest, still-live material reads
        # first; settled material (merged) follows.
        html = render_html(_bundle())
        active = html.index("<h2>Active discussions")
        issues = html.index("<h2>Issues")
        merged = html.index("<h2>Merged PRs")
        assert active < issues < merged

    def test_replies_fold_into_per_handle_details(self) -> None:
        posts = [
            _post("1", text="top-level note", handle="alice"),
            _post("2", text="first reply", handle="bob", reply_to="1"),
            _post("3", text="second reply", handle="bob", reply_to="1"),
        ]
        html = render_html(_bundle(x_posts=posts))
        assert "<summary>Replies from @bob (2)</summary>" in html
        # The top-level post stays in the visible list, above the fold.
        assert html.index("top-level note") < html.index("<details>")
        assert html.index("first reply") > html.index("<details>")

    def test_reply_folds_ordered_largest_first(self) -> None:
        posts = [
            _post("2", handle="alice", reply_to="1"),
            _post("3", handle="bob", reply_to="1"),
            _post("4", handle="bob", reply_to="1"),
        ]
        html = render_html(_bundle(x_posts=posts))
        assert html.index("Replies from @bob (2)") < html.index(
            "Replies from @alice (1)"
        )

    def test_only_replies_still_render_explicit_top_level_empty_line(
        self,
    ) -> None:
        html = render_html(_bundle(x_posts=[_post("2", reply_to="1")]))
        assert "No top-level posts this week." in html
        assert "Replies from @DukeOphir (1)" in html


class TestGlance:
    """The first-view dashboard: who moved / what's hot / where the talk is."""

    def test_glance_sits_between_snapshot_and_picks(self) -> None:
        html = render_html(_bundle())
        assert (
            html.index("This week at a glance") < html.index("<h2>Picks")
        )

    def test_actor_table_folds_bots_into_footnote(self) -> None:
        prs = [
            _pr(1, author="phdargen"),
            _pr(2, author="mintlify[bot]"),
            _pr(3, author="scotia1973-bot"),
        ]
        html = render_html(_bundle(prs=prs))
        assert "<td>@phdargen</td><td>1 merged</td>" in html
        assert "<td>@mintlify[bot]</td>" not in html
        assert "<td>@scotia1973-bot</td>" not in html
        assert "2 bot account(s), 2 item(s)" in html

    def test_x_movers_count_top_level_posts_only(self) -> None:
        posts = [
            _post("1", handle="alice"),
            _post("2", handle="alice", reply_to="1"),
        ]
        html = render_html(_bundle(x_posts=posts))
        assert "X top-level posts: @alice 1" in html

    def test_topic_distribution_shows_zero_and_uncategorised(self) -> None:
        rules = [
            TopicRule(
                key="specs",
                label="specs & schemes",
                scopes=("spec",),
                keywords=(),
            ),
            TopicRule(key="mcp", label="MCP", scopes=("mcp",), keywords=()),
        ]
        prs = [
            _pr(1, title="spec(xrpl): add scheme"),
            _pr(2, title="mystery work"),
        ]
        html = render_html(_bundle(prs=prs, topic_rules=rules))
        assert "<td>specs &amp; schemes</td><td>1</td>" in html
        # A tracked topic with no items this week stays visible at 0.
        assert "<td>MCP</td><td>0</td>" in html
        assert "<td>uncategorised</td><td>1</td>" in html

    def test_no_topic_rules_shows_explicit_unavailable_line(self) -> None:
        html = render_html(_bundle(prs=[_pr(1)]))
        assert "No topics config loaded" in html

    def test_x_keyword_line_includes_zero_buckets(self) -> None:
        kw = [XKeywordRule(key="mcp", label="MCP", patterns=("mcp",))]
        html = render_html(
            _bundle(x_posts=[_post("1", text="nothing here")], x_keywords=kw)
        )
        assert "X keyword hits: MCP 0" in html
