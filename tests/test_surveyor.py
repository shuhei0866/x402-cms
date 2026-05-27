"""Tests for `survey_week` — the candidate-surfacing helper.

`/x402-survey` is retrieval, not judgment: it groups a week's
indexed data so the curator sees the field before writing
commentary. Tests assert the SHAPE of the surfaced Markdown
(section headings, key data flowing through) rather than exact
prose — the prose may evolve, the contract is "the curator can
find X, Y, Z under labelled sections".
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from code.renderers.digest import COLLECTION, COMMENTARY_COLLECTION, X_COLLECTION
from code.survey.surveyor import survey_week


def _pr_dict(
    number: int,
    *,
    author: str = "phdargen",
    labels: list[str] | None = None,
    merged_at: datetime | None = None,
) -> dict:
    return {
        "repo": "x402-foundation/x402",
        "pr_number": number,
        "title": f"feat: thing {number}",
        "merged_at": (merged_at or datetime(2026, 5, 22, tzinfo=timezone.utc)).isoformat(),
        "author": author,
        "labels": labels or [],
        "url": f"https://github.com/x402-foundation/x402/pull/{number}",
        "week": "2026-W21",
    }


def _post_dict(
    post_id: str,
    *,
    handle: str = "DukeOphir",
    refs: list[str] | None = None,
) -> dict:
    return {
        "post_id": post_id,
        "author_handle": handle,
        "author_id": f"id-{handle}",
        "created_at": datetime(2026, 5, 22, tzinfo=timezone.utc).isoformat(),
        "text": f"tweet {post_id}",
        "url": f"https://x.com/{handle}/status/{post_id}",
        "week": "2026-W21",
        "referenced_prs": refs or [],
    }


def _commentary_dict(slug: str, target_refs: list[str]) -> dict:
    return {
        "slug": slug,
        "week": "2026-W21",
        "week_level": False,
        "target_refs": target_refs,
        "title": slug,
        "body_md": "body",
        "published": True,
        "published_at": datetime(2026, 5, 22, tzinfo=timezone.utc).isoformat(),
        "tags": [],
        "recommended_rank": None,
        "tldr": None,
    }


def _docs(payloads: list[dict]) -> list[MagicMock]:
    out: list[MagicMock] = []
    for p in payloads:
        m = MagicMock()
        m.to_dict.return_value = p
        out.append(m)
    return out


def _client(
    prs: list[dict] | None = None,
    posts: list[dict] | None = None,
    commentaries: list[dict] | None = None,
) -> MagicMock:
    pr_coll = MagicMock()
    pr_coll.where.return_value.stream.return_value = iter(_docs(prs or []))
    x_coll = MagicMock()
    x_coll.where.return_value.stream.return_value = iter(_docs(posts or []))
    c_coll = MagicMock()
    c_coll.where.return_value.stream.return_value = iter(_docs(commentaries or []))

    client = MagicMock()

    def route(name: str) -> MagicMock:
        return {
            COLLECTION: pr_coll,
            X_COLLECTION: x_coll,
            COMMENTARY_COLLECTION: c_coll,
        }[name]

    client.collection.side_effect = route
    return client


class TestSurveyWeekSnapshot:
    def test_snapshot_section_shows_top_line_counts(self) -> None:
        md = survey_week(
            "2026-W21",
            client=_client(
                prs=[_pr_dict(1), _pr_dict(2)],
                posts=[_post_dict("a"), _post_dict("b"), _post_dict("c")],
            ),
        )
        assert "# x402 weekly survey" in md
        assert "2026-W21" in md
        assert "## Snapshot" in md
        # counts surface as concrete numbers
        assert "2 PRs" in md
        assert "3 tweets" in md

    def test_snapshot_shows_cluster_distribution_when_clusters_known(self) -> None:
        md = survey_week(
            "2026-W21",
            client=_client(
                posts=[
                    _post_dict("a", handle="0x_natto"),
                    _post_dict("b", handle="0x_natto"),
                    _post_dict("c", handle="base"),
                ]
            ),
            handle_clusters={"0x_natto": "japan", "base": "protocol_core"},
        )
        assert "japan 2" in md
        assert "protocol_core 1" in md


class TestPRsWithoutCommentaryYet:
    def test_lists_prs_with_no_targeting_commentary(self) -> None:
        md = survey_week(
            "2026-W21",
            client=_client(
                prs=[_pr_dict(100), _pr_dict(101), _pr_dict(102)],
                commentaries=[
                    _commentary_dict(
                        "note-100",
                        target_refs=["pr:x402-foundation/x402#100"],
                    ),
                ],
            ),
        )
        # #100 has commentary; #101 + #102 do not.
        assert "## PRs without commentary yet" in md
        assert "#101" in md
        assert "#102" in md
        # #100 is covered → it appears in the snapshot count but not
        # in the gap list.
        gap_section = md.split("## PRs without commentary yet")[1].split("##")[0]
        assert "#100" not in gap_section


class TestCrossReferencesDrawn:
    def test_lists_pr_to_x_post_join(self) -> None:
        md = survey_week(
            "2026-W21",
            client=_client(
                prs=[_pr_dict(1944)],
                posts=[
                    _post_dict(
                        "tweet-1",
                        handle="DukeOphir",
                        refs=["x402-foundation/x402#1944"],
                    )
                ],
            ),
        )
        assert "## Cross-references already drawn" in md
        section = md.split("## Cross-references already drawn")[1].split("##")[0]
        assert "x402-foundation/x402#1944" in section
        assert "DukeOphir" in section


class TestActivePRAuthors:
    def test_groups_prs_by_author_with_counts_descending(self) -> None:
        md = survey_week(
            "2026-W21",
            client=_client(
                prs=[
                    _pr_dict(1, author="phdargen"),
                    _pr_dict(2, author="phdargen"),
                    _pr_dict(3, author="phdargen"),
                    _pr_dict(4, author="CarsonRoscoe"),
                ]
            ),
        )
        assert "## Active PR authors" in md
        section = md.split("## Active PR authors")[1].split("##")[0]
        # most-active first
        assert section.index("phdargen") < section.index("CarsonRoscoe")
        assert "phdargen" in section and "3" in section
        assert "CarsonRoscoe" in section and "1" in section


class TestXClusterActivity:
    def test_groups_posts_by_cluster_then_handle_with_counts(self) -> None:
        md = survey_week(
            "2026-W21",
            client=_client(
                posts=[
                    _post_dict("a", handle="0x_natto"),
                    _post_dict("b", handle="0x_natto"),
                    _post_dict("c", handle="base"),
                    _post_dict("d", handle="brto_0224"),
                ]
            ),
            handle_clusters={
                "0x_natto": "japan",
                "brto_0224": "japan",
                "base": "protocol_core",
            },
        )
        assert "## X cluster activity" in md
        section = md.split("## X cluster activity")[1]
        assert "japan" in section
        assert "0x_natto" in section and "2" in section
        assert "brto_0224" in section and "1" in section
        assert "protocol_core" in section
        assert "base" in section


class TestEmptyWeek:
    def test_empty_week_still_renders_all_section_headings(self) -> None:
        md = survey_week("2026-W21", client=_client())
        for heading in (
            "## Snapshot",
            "## PRs without commentary yet",
            "## Cross-references already drawn",
            "## Active PR authors",
            "## X cluster activity",
        ):
            assert heading in md
        # zero counts surface cleanly somewhere
        assert "0 PRs" in md
        assert "0 tweets" in md
