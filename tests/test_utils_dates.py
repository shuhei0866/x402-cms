"""Tests for ISO-week date helpers shared between indexers.

These three functions are the canonical translation layer between the
ISO-week labels the project speaks in (`"2026-W19"`) and the date /
datetime values the indexers actually operate on. Locking them down
here keeps both indexers honest about what "the previous week" means
and how a tweet's `created_at` maps to its bucket.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from code.utils.dates import parse_iso_week, previous_iso_week, week_of


class TestParseIsoWeek:
    def test_returns_monday_start_and_next_monday_exclusive_end(self) -> None:
        start, end = parse_iso_week("2026-W19")
        assert start == date(2026, 5, 4)
        # End is the following Monday, exclusive. Callers that want an
        # inclusive Sunday bound subtract one day themselves.
        assert end == date(2026, 5, 11)

    def test_iso_week_one_can_span_previous_calendar_year(self) -> None:
        # 2026-W01 begins on Mon 2025-12-29 because 2026-01-01 is a
        # Thursday inside that ISO week.
        start, end = parse_iso_week("2026-W01")
        assert start == date(2025, 12, 29)
        assert end == date(2026, 1, 5)

    def test_iso_week_53_in_a_53_week_year(self) -> None:
        # 2020 is one of the years with 53 ISO weeks; 2020-W53 is
        # Mon 2020-12-28 .. Sun 2021-01-03.
        start, end = parse_iso_week("2020-W53")
        assert start == date(2020, 12, 28)
        assert end == date(2021, 1, 4)

    def test_malformed_label_raises_valueerror(self) -> None:
        with pytest.raises(ValueError):
            parse_iso_week("not a week label")


class TestPreviousIsoWeek:
    """`today - 7 days` lands inside the previous ISO week for every
    weekday of `today`, so a Monday-morning Cloud Scheduler trigger
    picks last week and a mid-week manual run picks the same week."""

    def test_from_monday_returns_previous_week(self) -> None:
        # Mon 2026-05-11 is the start of W20 → previous = W19.
        assert previous_iso_week(today=date(2026, 5, 11)) == "2026-W19"

    def test_from_midweek_returns_previous_week(self) -> None:
        # Thu 2026-05-14 - 7d = Thu 2026-05-07 (still W19).
        assert previous_iso_week(today=date(2026, 5, 14)) == "2026-W19"

    def test_from_sunday_returns_previous_week(self) -> None:
        # Sun 2026-05-17 is the end of W20; - 7d = Sun 2026-05-10 (W19).
        assert previous_iso_week(today=date(2026, 5, 17)) == "2026-W19"

    def test_default_today_is_today_at_call_time(self) -> None:
        # No `today` arg = `date.today()`. We can only verify the
        # return shape without coupling the test to the wall clock.
        result = previous_iso_week()
        assert isinstance(result, str)
        assert "-W" in result


class TestWeekOf:
    def test_monday_start(self) -> None:
        assert week_of(datetime(2026, 5, 4, 0, 0, tzinfo=timezone.utc)) == "2026-W19"

    def test_sunday_end(self) -> None:
        assert week_of(datetime(2026, 5, 10, 23, 59, tzinfo=timezone.utc)) == "2026-W19"

    def test_next_monday_rolls_over(self) -> None:
        assert week_of(datetime(2026, 5, 11, 0, 0, tzinfo=timezone.utc)) == "2026-W20"

    def test_year_boundary_iso_week_one(self) -> None:
        # 2025-12-29 (Mon) is the start of 2026-W01 in ISO terms.
        assert week_of(datetime(2025, 12, 29, 0, 0, tzinfo=timezone.utc)) == "2026-W01"
