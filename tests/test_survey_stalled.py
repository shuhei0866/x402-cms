"""Tests for `find_stalled_prs` — the silence clock.

What is pinned here is the *definition* of stalled, because that is
what the view means and what a reader will trust: which PRs are in
scope, which timestamp the clock starts from, and where the boundary
sits. The prose that renders these rows lives in the surveyor tests.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from code.schemas.pr import PRRecord
from code.survey.stalled import (
    STALLED_AFTER_DAYS,
    find_stalled_prs,
    undatable_open_prs,
)

NOW = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)


def _pr(
    number: int,
    *,
    status: str = "open",
    created_at: datetime | None = None,
    last_maintainer_activity_at: datetime | None = None,
    responders: list[str] | None = None,
) -> PRRecord:
    return PRRecord(
        repo="x402-foundation/x402",
        pr_number=number,
        title=f"fix: thing {number}",
        author="shuhei0866",
        url=f"https://github.com/x402-foundation/x402/pull/{number}",
        week="2026-W21",
        status=status,
        kind="active",
        created_at=created_at,
        last_maintainer_activity_at=last_maintainer_activity_at,
        maintainer_responders=responders or [],
    )


def _days_ago(days: float) -> datetime:
    return NOW - timedelta(days=days)


class TestThreshold:
    def test_default_threshold_is_the_observed_worst_first_response(self) -> None:
        # The article's measurement: median first response 1.5 days,
        # slowest 8. The default has to be the slowest, so that silence
        # inside the observed range never reads as a signal.
        assert STALLED_AFTER_DAYS == 8

    def test_silence_beyond_the_threshold_is_listed(self) -> None:
        stalled = find_stalled_prs([_pr(1, created_at=_days_ago(9))], now=NOW)
        assert [s.pr.pr_number for s in stalled] == [1]
        assert stalled[0].silent_days == 9

    def test_silence_exactly_at_the_threshold_is_not(self) -> None:
        # "more than 8 days", so 8 days flat stays out.
        assert find_stalled_prs([_pr(1, created_at=_days_ago(8))], now=NOW) == []

    def test_boundary_is_elapsed_time_not_floored_days(self) -> None:
        # 8.5 days is more than 8 days even though `timedelta.days`
        # floors it back to 8.
        stalled = find_stalled_prs([_pr(1, created_at=_days_ago(8.5))], now=NOW)
        assert [s.pr.pr_number for s in stalled] == [1]
        assert stalled[0].silent_days == 8

    def test_threshold_is_overridable(self) -> None:
        prs = [_pr(1, created_at=_days_ago(4))]
        assert find_stalled_prs(prs, now=NOW) == []
        assert len(find_stalled_prs(prs, now=NOW, threshold_days=3)) == 1


class TestClockAnchor:
    def test_maintainer_reaction_restarts_the_clock(self) -> None:
        # Opened 30 days ago but answered 3 days ago: not stalled.
        prs = [
            _pr(
                1,
                created_at=_days_ago(30),
                last_maintainer_activity_at=_days_ago(3),
                responders=["phdargen"],
            )
        ]
        assert find_stalled_prs(prs, now=NOW) == []

    def test_stale_maintainer_reaction_is_reported_as_such(self) -> None:
        prs = [
            _pr(
                1,
                created_at=_days_ago(60),
                last_maintainer_activity_at=_days_ago(20),
                responders=["phdargen"],
            )
        ]
        (stalled,) = find_stalled_prs(prs, now=NOW)
        assert stalled.anchor == "maintainer"
        assert stalled.silent_days == 20

    def test_never_answered_pr_runs_from_creation(self) -> None:
        (stalled,) = find_stalled_prs([_pr(1, created_at=_days_ago(12))], now=NOW)
        assert stalled.anchor == "created"
        assert stalled.since == _days_ago(12)


class TestScope:
    def test_merged_and_closed_rows_are_out_of_scope(self) -> None:
        prs = [
            _pr(1, status="merged", created_at=_days_ago(30)),
            _pr(2, status="closed", created_at=_days_ago(30)),
            _pr(3, status="open", created_at=_days_ago(30)),
            _pr(4, status="draft", created_at=_days_ago(30)),
        ]
        assert {s.pr.pr_number for s in find_stalled_prs(prs, now=NOW)} == {3, 4}

    def test_undatable_rows_are_excluded_not_assumed_stalled(self) -> None:
        # A row indexed before enrichment with no `created_at` cannot be
        # dated; silently listing it would invent a stall.
        prs = [_pr(1, created_at=None)]
        assert find_stalled_prs(prs, now=NOW) == []
        assert [pr.pr_number for pr in undatable_open_prs(prs)] == [1]

    def test_undatable_only_counts_open_rows(self) -> None:
        prs = [_pr(1, status="merged", created_at=None)]
        assert undatable_open_prs(prs) == []


class TestOrdering:
    def test_longest_silence_first(self) -> None:
        prs = [
            _pr(1, created_at=_days_ago(10)),
            _pr(2, created_at=_days_ago(40)),
            _pr(3, created_at=_days_ago(20)),
        ]
        assert [s.pr.pr_number for s in find_stalled_prs(prs, now=NOW)] == [2, 3, 1]
