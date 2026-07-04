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


def _active(number: int) -> PRRecord:
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
        comments=7,
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
        assert '<h2 id="active">Active discussions (1)</h2>' in html
        assert '<h2 id="new">Newly opened (1)</h2>' in html
        assert '<h2 id="issues">Issues (1)</h2>' in html

    def test_active_row_shows_status_and_comments(self) -> None:
        html = render_html(_bundle(active_prs=[_active(2)]))
        assert "#2" in html
        assert "open, 7 comments" in html

    def test_new_row_shows_opened_date(self) -> None:
        html = render_html(_bundle(new_prs=[_new(3)]))
        assert "opened 2026-05-07" in html

    def test_issue_row_shows_comments(self) -> None:
        html = render_html(_bundle(issues=[_issue(50)]))
        assert "#50" in html
        assert "12 comments" in html

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
        hot = html[html.index("What's hot") : html.index("Where the talk is")]
        assert hot.index("#50") < hot.index("#2")
        assert "12 comments (issue)" in hot
        assert "7 comments (PR)" in hot

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
