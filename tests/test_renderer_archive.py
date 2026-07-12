"""Human-first home, archive, and missing-edition views."""

from __future__ import annotations

from datetime import datetime, timezone

from code.renderers.digest import (
    PublishedEdition,
    render_archive,
    render_home,
    render_not_found,
)


def _edition(week: str, title: str) -> PublishedEdition:
    return PublishedEdition(
        week=week,
        title=title,
        published_at=datetime(2026, 7, 13, tzinfo=timezone.utc),
    )


def test_home_leads_with_latest_title_and_calendar_dates() -> None:
    html = render_home(
        [
            _edition("2026-W28", "The operational design after payment"),
            _edition("2026-W24", "Migration paths before features"),
        ]
    )

    assert "The operational design after payment" in html
    assert "Jul 6–12, 2026" in html
    assert html.index("2026-W28") < html.index("2026-W24")


def test_home_with_one_edition_does_not_claim_there_are_none() -> None:
    html = render_home([_edition("2026-W28", "Only edition")])
    assert "Only edition" in html
    assert "No published editions yet." not in html


def test_archive_lists_only_supplied_editions_and_preserves_gaps() -> None:
    html = render_archive(
        [
            _edition("2026-W28", "Latest"),
            _edition("2026-W24", "Earlier"),
        ]
    )

    assert "/digest/2026-W28?lang=en" in html
    assert "/digest/2026-W24?lang=en" in html
    assert "2026-W27" not in html


def test_archive_empty_state_is_explicit() -> None:
    html = render_archive([])
    assert "No published editions yet." in html


def test_japanese_archive_uses_calendar_dates() -> None:
    html = render_archive(
        [_edition("2026-W28", "決済の先に残る、運用の設計")], lang="ja"
    )
    assert "2026年7月6日〜7月12日" in html
    assert "記事一覧" in html


def test_archive_keeps_a_language_toggle() -> None:
    html = render_archive([_edition("2026-W28", "Latest")], lang="en")
    assert "/archive?lang=ja" in html
    assert "日本語" in html


def test_not_found_links_to_latest_and_archive() -> None:
    html = render_not_found(
        "2026-W26",
        [_edition("2026-W28", "Latest")],
        lang="en",
    )
    assert "This edition is not published." in html
    assert "/digest/2026-W28?lang=en" in html
    assert "/archive?lang=en" in html
