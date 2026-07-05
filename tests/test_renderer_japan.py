"""Tests for the Japan community section in the renderer.

The cluster label `japan` is the bridge between the curated handle
list and a renderer-side spotlight: every X post whose author handle
maps to `japan` in `bundle.handle_clusters` lands in the section.

Contract:
- HTML always renders a `Japan community` `<h2>` (with empty state
  copy when the section has zero posts) so the page shape is stable
  across slow weeks and across deploys with no curation.
- agent JSON always has a `japan_section` key — a list of full post
  dicts (denormalised, parallel to `x_posts`) so an agent does not
  have to re-join by cluster.
- Section position: after the X posts section, before
  cross-references. JP posts are a deeper cut of X posts, not a
  parallel data source, so they live next to X.
"""

from __future__ import annotations

from datetime import datetime, timezone

from code.renderers.digest import DigestBundle, render_agent_payload, render_html
from code.schemas.x_post import XPost


def _post(post_id: str, handle: str, *, week: str = "2026-W21") -> XPost:
    return XPost(
        post_id=post_id,
        author_handle=handle,
        author_id=f"id-{handle}",
        created_at=datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc),
        text=f"a post from {handle}",
        url=f"https://x.com/{handle}/status/{post_id}",
        week=week,
    )


def _bundle(
    *,
    x_posts: list[XPost] | None = None,
    handle_clusters: dict[str, str] | None = None,
    week: str = "2026-W21",
) -> DigestBundle:
    return DigestBundle(
        week=week,
        repo="x402-foundation/x402",
        prs=[],
        x_posts=x_posts or [],
        cross_references=[],
        handle_clusters=handle_clusters or {},
    )


class TestJapanSectionHtml:
    def test_jp_handles_with_posts_appear_in_japan_section(self) -> None:
        bundle = _bundle(
            x_posts=[_post("a", "0x_natto"), _post("b", "winor30"), _post("c", "base")],
            handle_clusters={
                "0x_natto": "japan",
                "winor30": "japan",
                "base": "protocol_core",
            },
        )
        html = render_html(bundle)
        assert (
            '<span class="sname">Japan community</span> '
            '<span class="count">2</span>'
        ) in html
        # The JP section lists the two JP posts, not the protocol_core
        # post.
        assert "@0x_natto" in html
        assert "@winor30" in html

    def test_japan_section_appears_after_x_posts_before_cross_references(self) -> None:
        bundle = _bundle(
            x_posts=[_post("a", "0x_natto")],
            handle_clusters={"0x_natto": "japan"},
        )
        html = render_html(bundle)
        assert (
            html.index("X posts")
            < html.index("Japan community")
            < html.index("Cross-references")
        )

    def test_no_jp_posts_shows_explicit_empty_state(self) -> None:
        bundle = _bundle(
            x_posts=[_post("a", "base")],
            handle_clusters={"base": "protocol_core"},
        )
        html = render_html(bundle)
        assert (
            '<span class="sname">Japan community</span> '
            '<span class="count">0</span>'
        ) in html
        assert "No Japan community posts this week" in html

    def test_no_handle_clusters_still_renders_empty_jp_section(self) -> None:
        # OSS clone without curation: handle_clusters is empty.
        # Section still shows so HTML shape is stable across deploys.
        bundle = _bundle(x_posts=[_post("a", "base")])
        html = render_html(bundle)
        assert "Japan community" in html
        assert "No Japan community posts" in html


class TestJapanSectionAgentPayload:
    def test_japan_section_key_always_present(self) -> None:
        bundle = _bundle()
        payload = render_agent_payload(bundle)
        assert "japan_section" in payload
        assert payload["japan_section"] == []

    def test_japan_section_contains_full_post_dicts_for_jp_handles(self) -> None:
        bundle = _bundle(
            x_posts=[_post("a", "0x_natto"), _post("b", "base")],
            handle_clusters={"0x_natto": "japan", "base": "protocol_core"},
        )
        payload = render_agent_payload(bundle)
        assert len(payload["japan_section"]) == 1
        row = payload["japan_section"][0]
        assert row["post_id"] == "a"
        assert row["author_handle"] == "0x_natto"
        # Denormalised: the row is a full XPost dump, not a slug ref.
        assert "text" in row and "created_at" in row

    def test_payload_keys_still_pinned_with_japan_section_added(self) -> None:
        # The Phase-4 key set + japan_section. Pin exact so a future
        # accidental rename trips it.
        bundle = _bundle()
        payload = render_agent_payload(bundle)
        assert set(payload.keys()) == {
            "week",
            "repo",
            "count",
            "merged_prs",
            "active_prs",
            "new_prs",
            "issues",
            "x_posts",
            "cross_references",
            "commentary",
            "agent_recommendations",
            "japan_section",
        }
