"""Which open PRs have gone quiet, and for how long.

Pure computation over rows the indexer already wrote — no network, no
judgment. The survey renders the result; deciding whether a quiet PR
deserves a nudge, an offer to take it over, or nothing at all stays
with the human, as everywhere else in this tool.

The 8-day threshold is not a guess. Measured over one contributor's
run of PRs against the x402 repositories, the first maintainer response
came after 1.5 days at the median and 8 days at the worst. So silence
under 8 days is inside the observed normal range and says nothing;
silence past it is the first point where the data stops explaining
itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from code.schemas.pr import PRRecord

STALLED_AFTER_DAYS = 8

OPEN_STATUSES = frozenset({"open", "draft"})

SilenceAnchor = Literal["maintainer", "created"]


@dataclass
class StalledPR:
    """One open PR nobody from the project has answered lately."""

    pr: PRRecord
    silent_days: int
    """Whole days of silence, floored — the display figure."""

    since: datetime
    """The moment the silence started running."""

    anchor: SilenceAnchor
    """`maintainer` when a maintainer did react once and then went
    quiet, `created` when none ever has — the difference between "the
    conversation stopped" and "it never started"."""


def find_stalled_prs(
    prs: list[PRRecord],
    *,
    now: datetime | None = None,
    threshold_days: int = STALLED_AFTER_DAYS,
) -> list[StalledPR]:
    """Return the still-open PRs silent for longer than `threshold_days`.

    The clock runs from the last maintainer reaction, or from the PR's
    creation when there has never been one — the case the threshold was
    measured on. Closed and merged rows are out of scope, and so is any
    row carrying neither timestamp (a row indexed before enrichment can
    still date itself by `created_at`; one with nothing to date is
    counted by the caller, not silently treated as stalled).

    Longest silence first.
    """
    now = now or datetime.now(timezone.utc)
    stalled: list[StalledPR] = []
    for pr in prs:
        if pr.status not in OPEN_STATUSES:
            continue
        since = pr.last_maintainer_activity_at or pr.created_at
        if since is None:
            continue
        anchor: SilenceAnchor = (
            "maintainer" if pr.last_maintainer_activity_at else "created"
        )
        silence = now - since
        # Compare on the real elapsed time, not the floored day count,
        # so "more than 8 days" means what it says.
        if silence.total_seconds() / 86400 <= threshold_days:
            continue
        stalled.append(
            StalledPR(
                pr=pr,
                silent_days=silence.days,
                since=since,
                anchor=anchor,
            )
        )
    stalled.sort(key=lambda s: s.since)
    return stalled


def undatable_open_prs(prs: list[PRRecord]) -> list[PRRecord]:
    """Open PRs the silence clock cannot be started on.

    Surfaced as a coverage note so an empty stalled list is never read
    as "nothing is stalled" when it might mean "nothing is measurable".
    """
    return [
        pr
        for pr in prs
        if pr.status in OPEN_STATUSES
        and pr.last_maintainer_activity_at is None
        and pr.created_at is None
    ]
