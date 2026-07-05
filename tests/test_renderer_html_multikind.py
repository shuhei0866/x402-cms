"""Tests for the active / new PR and issue sections of the HTML view.

The multi-kind indexer adds three GitHub-activity sections after
Merged PRs: Active discussions, Newly opened, and Issues. Each shows
its count, renders an explicit "no … this week" line when empty, and
the active / new PR rows accept the same inline single-target
commentary that merged PRs do (keyed on the `pr:repo#N` token).
"""

from __future__ import annotations

from datetime import datetime, timezone

from code.renderers.digest import DigestBundle, render_html
from code.schemas.commentary import Commentary
from code.schemas.issue import IssueRecord
from code.schemas.pr import PRRecord

D = datetime(2026, 5, 7, tzinfo=timezone.utc)


def _active(number: int, *, comments: int = 7) -> PRRecord:
    return PRRecord(
        repo="x402-foundation/x402",
        pr_number=number,
        title=f"wip {number}",
        author="phdargen",
        url=f"https://github.com/x402-foundation/x402/pull/{number}",
        week="2026-W19",
        status="open",
        kind="active",
        updated_at=D,
        comments=comments,
    )


def _new(number: int, *, status: str = "open") -> PRRecord:
    return PRRecord(
        repo="x402-foundation/x402",
        pr_number=number,
        title=f"new {number}",
        author="someone",
        url=f"https://github.com/x402-foundation/x402/pull/{number}",
        week="2026-W19",
        status=status,
        kind="new",
        created_at=D,
    )


def _issue(number: int) -> IssueRecord:
    return IssueRecord(
        repo="x402-foundation/x402",
        issue_number=number,
        title=f"discussion {number}",
        author="someone",
        url=f"https://github.com/x402-foundation/x402/issues/{number}",
        week="2026-W19",
        state="open",
        kind="active",
        comments=12,
        updated_at=D,
    )


def _bundle(**kw) -> DigestBundle:
    return DigestBundle(
        week="2026-W19",
        repo="x402-foundation/x402",
        prs=[],
        x_posts=[],
        cross_references=[],
        active_prs=kw.get("active_prs", []),
        new_prs=kw.get("new_prs", []),
        issues=kw.get("issues", []),
        commentaries=kw.get("commentaries", []),
    )


class TestSectionsRender:
    def test_section_headings_carry_counts(self) -> None:
        html = render_html(
            _bundle(active_prs=[_active(2)], new_prs=[_new(3)], issues=[_issue(50)])
        )
        assert '<details class="section" id="active">' in html
        assert (
            '<span class="sname">Active discussions</span> '
            '<span class="count">1</span>'
        ) in html
        assert (
            '<span class="sname">Newly opened</span> <span class="count">1</span>'
        ) in html
        assert (
            '<span class="sname">Issues</span> <span class="count">1</span>'
        ) in html

    def test_active_row_shows_status_and_comments(self) -> None:
        # Comment count is the heat number; status rides the muted meta.
        html = render_html(_bundle(active_prs=[_active(2)]))
        assert "#2" in html
        assert '<span class="n">7</span>' in html
        assert "· open ·" in html

    def test_new_row_shows_opened_date(self) -> None:
        html = render_html(_bundle(new_prs=[_new(3)]))
        assert "opened May 7" in html

    def test_issue_row_shows_comments(self) -> None:
        html = render_html(_bundle(issues=[_issue(50)]))
        assert "#50" in html
        assert '<span class="n">12</span>' in html

    def test_empty_sections_render_explicit_lines(self) -> None:
        html = render_html(_bundle())
        assert "No active discussions this week." in html
        assert "No newly opened PRs this week." in html
        assert "No active issues this week." in html

    def test_whats_hot_ranks_prs_and_issues_by_comments(self) -> None:
        # Issue #50 (12 comments) outranks PR #2 (7 comments) in the
        # glance list — kinds compete in one ranking.
        html = render_html(
            _bundle(active_prs=[_active(2)], issues=[_issue(50)])
        )
        hot = html[html.index("hot</h3>") : html.index("Where the talk is")]
        assert hot.index("#50") < hot.index("#2")
        # Heat numbers carry the count; the row is compact (no meta).
        assert '<span class="n">12</span>' in hot
        assert '<span class="n">7</span>' in hot

    def test_heat_bar_scales_to_section_max(self) -> None:
        # The bar width encodes comment count relative to the section's
        # top row: the busiest thread fills the track, a half-as-busy
        # one fills half. This is the design layer's one bit of real
        # logic, so it gets pinned.
        html = render_html(
            _bundle(active_prs=[_active(1, comments=10), _active(2, comments=5)])
        )
        assert 'style="--w:100%"' in html
        assert 'style="--w:50%"' in html

    def test_merged_and_new_rows_carry_state_tags_not_heat(self) -> None:
        # Merged / newly-opened rows carry no comment heat (settled /
        # brand new), so they show a state tag instead of a bar.
        from code.schemas.pr import MergedPR

        merged = MergedPR(
            repo="x402-foundation/x402",
            pr_number=9,
            title="ship it",
            merged_at=D,
            author="phdargen",
            labels=[],
            url="https://github.com/x402-foundation/x402/pull/9",
            week="2026-W19",
        )
        html = render_html(DigestBundle(
            week="2026-W19",
            repo="x402-foundation/x402",
            prs=[merged],
            x_posts=[],
            cross_references=[],
            new_prs=[_new(3)],
        ))
        assert '<span class="label">merged</span>' in html
        assert '<span class="label">new</span>' in html

    def test_new_closed_rows_fold_into_details(self) -> None:
        # Newly opened PRs that were already closed (the ecosystem-
        # listing wave) fold away; still-open rows stay visible.
        html = render_html(
            _bundle(new_prs=[_new(3), _new(4, status="closed")])
        )
        assert "<summary>Closed without merge (1)</summary>" in html
        assert html.index("new 3") < html.index("<details>")
        assert html.index("new 4") > html.index("<details>")

    def test_new_all_closed_keeps_explicit_open_empty_line(self) -> None:
        html = render_html(_bundle(new_prs=[_new(4, status="closed")]))
        assert "No still-open PRs this week." in html
        assert "<summary>Closed without merge (1)</summary>" in html

    def test_active_pr_accepts_inline_commentary(self) -> None:
        # A single-target note on an active PR inlines as a blockquote,
        # exactly like it does on a merged PR — same `pr:repo#N` token.
        note = Commentary(
            slug="note-on-2",
            week="2026-W19",
            week_level=False,
            target_refs=["pr:x402-foundation/x402#2"],
            title="why this matters",
            body_md="worth watching",
            published=True,
            recommended_rank=None,
            tldr=None,
        )
        html = render_html(_bundle(active_prs=[_active(2)], commentaries=[note]))
        assert 'id="commentary-note-on-2"' in html
        assert "worth watching" in html
