"""Tests for `render_html(bundle)`.

The HTML is still deliberately minimal — Phase 4's commentary layer
will dress it up. Phase 2's contract: the three sections (merged PRs,
X posts, cross-references) appear with their data, empty sections
render an explicit "no … this week" line so the page is never
silently truncated, and PR + X post fields are HTML-escaped.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from code.renderers.digest import (
    CrossReference,
    DigestBundle,
    PublishedEdition,
    render_html,
)
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
        html = render_html(
            _bundle(prs=[_pr(1944, title="feat: TVM scheme", author="ArkadiyStena")])
        )
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
                CrossReference(
                    pr_ref="x402-foundation/x402#1944", x_post_ids=["12345"]
                ),
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
        # The tweet's own script is escaped to an inert entity; the
        # page's trusted hash-open script is the only real <script>.
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html

    def test_head_links_vendored_stylesheet_and_viewport(self) -> None:
        # The human view is styled by the vendored classless Pico
        # stylesheet; the markup itself stays class-free.
        html = render_html(_bundle())
        assert '<link rel="stylesheet" href="/static/pico.classless.min.css">' in html
        assert '<meta name="viewport"' in html

    def test_body_content_is_wrapped_in_main(self) -> None:
        # Pico's classless layout keys its container on `body > main`.
        html = render_html(_bundle())
        assert "<main>" in html
        assert "</main>" in html

    def test_head_links_digest_design_stylesheet(self) -> None:
        # The design layer rides on top of classless Pico via a second
        # vendored stylesheet.
        html = render_html(_bundle())
        assert '<link rel="stylesheet" href="/static/digest.css">' in html

    def test_snapshot_is_a_marker_free_strip(self) -> None:
        # The snapshot is a div/span strip, not a <ul>, so Pico's list
        # bullets never leak into it.
        html = render_html(_bundle())
        assert '<div class="snapshot">' in html

    def test_body_sections_are_collapsed_by_default(self) -> None:
        # The page is glance-first: every body section folds into a
        # <details> that starts closed, so the reader lands on one
        # focused screen instead of a long uniform scroll.
        html = render_html(_bundle())
        assert '<details class="section" id="active">' in html
        assert '<details class="section" id="x-posts">' in html
        # Closed by default — no `open` attribute on a section.
        assert '<details class="section" id="active" open>' not in html

    def test_glance_and_picks_stay_open_above_the_fold(self) -> None:
        # The dashboard and the curated picks are the focus; they are
        # never collapsed.
        html = render_html(_bundle())
        assert '<h2 id="glance">' in html
        assert '<h2 id="picks">' in html
        assert '<details class="section" id="glance">' not in html

    def test_hash_open_script_present(self) -> None:
        # Progressive enhancement so a nav / deep link opens its target
        # section. The page still works with no JS.
        html = render_html(_bundle())
        assert 'addEventListener("hashchange", openTarget)' in html


class TestInformationDesign:
    """Snapshot line, section order, and the reply / closed folds."""

    def test_snapshot_line_summarises_the_week(self) -> None:
        html = render_html(
            _bundle(
                prs=[_pr(1)],
                x_posts=[_post("1"), _post("2", reply_to="1")],
            )
        )
        assert "<b>1</b> merged" in html
        assert "<b>0</b> active" in html
        assert "<b>0</b> newly opened" in html
        assert "<b>0</b> issues" in html
        assert "<b>1</b> X posts" in html
        assert "+ 1 replies" in html

    def test_discussion_sections_come_before_merged(self) -> None:
        # Inverted pyramid: the hottest, still-live material reads
        # first; settled material (merged) follows.
        html = render_html(_bundle())
        active = html.index('id="active"')
        issues = html.index('id="issues"')
        merged = html.index('id="merged"')
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
        assert html.index("This week at a glance") < html.index('<h2 id="picks">Picks')

    def test_actor_table_folds_bots_into_footnote(self) -> None:
        prs = [
            _pr(1, author="phdargen"),
            _pr(2, author="mintlify[bot]"),
            _pr(3, author="scotia1973-bot"),
        ]
        html = render_html(_bundle(prs=prs))
        assert '<span class="who">@phdargen</span>' in html
        assert '<span class="what">1 merged</span>' in html
        assert "@mintlify[bot]</span>" not in html
        assert "@scotia1973-bot</span>" not in html
        assert "2 bot account(s) · 2 item(s) · folded" in html

    def test_x_movers_count_top_level_posts_only(self) -> None:
        posts = [
            _post("1", handle="alice"),
            _post("2", handle="alice", reply_to="1"),
        ]
        html = render_html(_bundle(x_posts=posts))
        assert "X: @alice 1" in html

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
        assert '<span class="dlabel">specs &amp; schemes</span>' in html
        assert '<span class="dnum">1</span>' in html
        # A tracked topic with no items this week stays visible at 0.
        assert '<span class="dlabel">MCP</span>' in html
        assert '<span class="dnum">0</span>' in html
        assert '<span class="dlabel">uncategorised</span>' in html

    def test_no_topic_rules_shows_explicit_unavailable_line(self) -> None:
        html = render_html(_bundle(prs=[_pr(1)]))
        assert "No topics config loaded" in html

    def test_x_keyword_line_includes_zero_buckets(self) -> None:
        kw = [XKeywordRule(key="mcp", label="MCP", patterns=("mcp",))]
        html = render_html(
            _bundle(x_posts=[_post("1", text="nothing here")], x_keywords=kw)
        )
        assert "X keywords: MCP 0" in html


class TestPageNavigation:
    """Week links and the section nav that close the round-trip loop."""

    def test_week_nav_links_to_adjacent_weeks(self) -> None:
        # The bundle fixture week is 2026-W19. Generated links pin the
        # locale so the choice survives navigation on any browser.
        html = render_html(_bundle())
        assert '<a href="/digest/2026-W18?lang=en">' in html
        assert '<a href="/digest/2026-W20?lang=en">' in html

    def test_published_navigation_skips_week_gaps(self) -> None:
        editions = [
            PublishedEdition("2026-W20", "Newer", None),
            PublishedEdition("2026-W19", "Current", None),
            PublishedEdition("2026-W15", "Older", None),
        ]

        html = render_html(_bundle(), published_editions=editions)

        assert "/digest/2026-W15?lang=en" in html
        assert "/digest/2026-W20?lang=en" in html
        assert "/digest/2026-W18" not in html

    def test_section_nav_targets_all_resolve_to_ids(self) -> None:
        # Every href="#…" in the nav must have a matching id on the
        # page — the integrity check that keeps the hub honest.
        html = render_html(_bundle())
        nav = html[html.index('<nav class="sectionnav"') : html.index("</nav>")]
        targets = re.findall(r'href="#([\w-]+)"', nav)
        ids = set(re.findall(r'id="([\w-]+)"', html))
        assert len(targets) == 10
        assert all(target in ids for target in targets)

    def test_malformed_week_renders_without_week_nav(self) -> None:
        bundle = _bundle()
        bundle.week = "not-a-week"
        html = render_html(bundle)
        assert "not-a-week" in html
        # No computed prev / next links (their arrows are absent). The
        # language toggle may still link to the same malformed week.
        assert "←" not in html
        assert "→" not in html


class TestLocalisation:
    """The Japanese chrome; the rows themselves stay in source language."""

    def test_english_is_the_default(self) -> None:
        html = render_html(_bundle())
        assert '<html lang="en">' in html
        assert "This week at a glance" in html

    def test_japanese_localises_the_chrome(self) -> None:
        html = render_html(_bundle(), lang="ja")
        assert '<html lang="ja">' in html
        assert "今週のまとめ" in html
        assert "This week at a glance" not in html
        assert '<span class="sname">アクティブな議論</span>' in html

    def test_row_content_is_never_translated(self) -> None:
        # A PR title is upstream source data — it stays as written even
        # in the Japanese view.
        html = render_html(
            _bundle(prs=[_pr(1944, title="feat: TVM scheme")]), lang="ja"
        )
        assert "feat: TVM scheme" in html

    def test_toggle_points_to_the_other_locale(self) -> None:
        # Fixture week is 2026-W19. The toggle pins the *other* locale
        # explicitly, so it works even on an Accept-Language-selected
        # page (a bare English link would resolve back to Japanese).
        en = render_html(_bundle())
        assert 'class="langtoggle" href="/digest/2026-W19?lang=ja">日本語' in en
        ja = render_html(_bundle(), lang="ja")
        assert 'class="langtoggle" href="/digest/2026-W19?lang=en">English' in ja

    def test_week_nav_carries_the_locale_in_both_directions(self) -> None:
        # The chosen language persists across week navigation, English
        # included — a bare link would fall back to Accept-Language.
        ja = render_html(_bundle(), lang="ja")
        assert '<a href="/digest/2026-W20?lang=ja">' in ja
        en = render_html(_bundle())
        assert '<a href="/digest/2026-W20?lang=en">' in en

    def test_unknown_lang_falls_back_to_english(self) -> None:
        html = render_html(_bundle(), lang="fr")
        assert '<html lang="en">' in html
        assert "This week at a glance" in html

    def test_nav_aria_label_is_localised_without_breaking_the_css_hook(
        self,
    ) -> None:
        # The screen-reader label is chrome (localised); the CSS keys
        # off the stable `sectionnav` class, not the aria-label.
        en = render_html(_bundle())
        assert '<nav class="sectionnav" aria-label="sections">' in en
        ja = render_html(_bundle(), lang="ja")
        assert 'class="sectionnav"' in ja
        assert 'aria-label="セクション"' in ja
