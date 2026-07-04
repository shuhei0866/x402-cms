"""ISO-week helpers shared by the indexers and the renderer.

Three small functions translate between the project's two
date representations: the ISO-week label (`"YYYY-Www"`, what the
digest is bucketed by) and the underlying `date` / `datetime`
values. Centralising them here keeps every pipeline component
agreeing on what "the previous week" means and how a row's
`created_at` maps to its bucket.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta


def parse_iso_week(week: str) -> tuple[date, date]:
    """Return `[start, end)` date bounds for an ISO week label.

    Start is the Monday of that ISO week; end is the following Monday
    (exclusive), so callers building inclusive ranges subtract one day
    themselves. Raises `ValueError` for malformed labels.
    """
    year_str, week_str = week.split("-W")
    start = date.fromisocalendar(int(year_str), int(week_str), 1)
    end = start + timedelta(days=7)
    return start, end


def previous_iso_week(today: date | None = None) -> str:
    """Return the ISO week label for the week ending most recently.

    `today - 7 days` lands inside the previous ISO week regardless of
    which weekday `today` is, so a Monday-morning Cloud Scheduler
    trigger picks last week and a mid-week manual run picks the same
    week as last Monday's run did.
    """
    anchor = (today or date.today()) - timedelta(days=7)
    iso_year, iso_week, _ = anchor.isocalendar()
    return f"{iso_year:04d}-W{iso_week:02d}"


def current_iso_week(today: date | None = None) -> str:
    """Return the ISO week label for the week in progress.

    The complement of `previous_iso_week`: a mid-week Cloud Scheduler
    trigger picks the week it runs in, so an intra-week run refreshes
    the digest for the week that is still accumulating rather than
    re-indexing the one that already closed.
    """
    iso_year, iso_week, _ = (today or date.today()).isocalendar()
    return f"{iso_year:04d}-W{iso_week:02d}"


def resolve_target_week(
    week: str | None, current: bool, today: date | None = None
) -> str:
    """Pick the ISO week an indexer run targets.

    Precedence: an explicit `--week` label wins; otherwise `--current`
    selects the in-progress week; otherwise the default is the previous
    (just-closed) week. Centralised so every indexer's `--week` /
    `--current` flags resolve the same way.
    """
    if week:
        return week
    if current:
        return current_iso_week(today)
    return previous_iso_week(today)


def week_of(created_at: datetime) -> str:
    """Return the ISO week label (`YYYY-Www`) for a timestamp.

    Pure on the input — no `today()` reference — so a re-run over the
    same window produces the same bucket label for every row.
    """
    iso_year, iso_week, _ = created_at.isocalendar()
    return f"{iso_year:04d}-W{iso_week:02d}"


def shift_iso_week(week: str, delta: int) -> str:
    """Return the ISO week label `delta` weeks away from `week`.

    Pure label arithmetic (via the week's Monday), so year boundaries
    and 53-week years resolve the way `isocalendar` says they do.
    Raises `ValueError` for malformed labels, like `parse_iso_week`.
    """
    start, _ = parse_iso_week(week)
    shifted = start + timedelta(weeks=delta)
    iso_year, iso_week, _ = shifted.isocalendar()
    return f"{iso_year:04d}-W{iso_week:02d}"
