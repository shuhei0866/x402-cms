"""Tests for `survey_week` — the candidate-surfacing helper.

`/x402-survey` is retrieval, not judgment: it groups a week's
indexed data so the curator sees the field before writing
commentary. Tests assert the SHAPE of the surfaced Markdown
(section headings, key data flowing through) rather than exact
prose — the prose may evolve, the contract is "the curator can
find X, Y, Z under labelled sections".

The two scouting sections (stalled PRs, cross-SDK parity gaps) are
tested the same way. Their rules live in `test_survey_stalled` and
`test_survey_parity`; what is pinned here is that the rows reach the
Markdown, under their heading, carrying what a human needs to act —
and that an incomplete index says so instead of reading as an
all-clear.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from code.renderers.digest import COLLECTION, COMMENTARY_COLLECTION, X_COLLECTION
from code.survey.surveyor import survey_week

NOW = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)


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


def _open_pr_dict(
    number: int,
    *,
    title: str | None = None,
    author: str = "shuhei0866",
    status: str = "open",
    created_at: datetime | None = None,
    last_maintainer_activity_at: datetime | None = None,
    responders: list[str] | None = None,
    changed_paths: list[str] | None = None,
) -> dict:
    """A row as the multi-kind indexer writes it after enrichment."""
    return {
        "repo": "x402-foundation/x402",
        "pr_number": number,
        "title": title or f"fix: thing {number}",
        "author": author,
        "url": f"https://github.com/x402-foundation/x402/pull/{number}",
        "week": "2026-W21",
        "status": status,
        "kind": "active",
        "merged_at": None,
        "created_at": (created_at or datetime(2026, 5, 1, tzinfo=timezone.utc)).isoformat(),
        "updated_at": None,
        "comments": 0,
        "labels": [],
        "changed_paths": changed_paths or [],
        "paths_truncated": False,
        "last_maintainer_activity_at": (
            last_maintainer_activity_at.isoformat() if last_maintainer_activity_at else None
        ),
        "maintainer_responders": responders or [],
    }


def _docs(payloads: list[dict]) -> list[MagicMock]:
    out: list[MagicMock] = []
    for p in payloads:
        m = MagicMock()
        m.to_dict.return_value = p
        out.append(m)
    return out


def _stream_factory(payloads: list[dict]):
    """A `.stream()` that can be called more than once.

    `source_data` is read twice per survey — once narrowed to merged
    rows, once for every kind — so a one-shot iterator would leave the
    second reader looking at an empty week.
    """
    return lambda *_args, **_kwargs: iter(_docs(payloads))


def _client(
    prs: list[dict] | None = None,
    posts: list[dict] | None = None,
    commentaries: list[dict] | None = None,
) -> MagicMock:
    pr_coll = MagicMock()
    pr_coll.where.return_value.stream.side_effect = _stream_factory(prs or [])
    x_coll = MagicMock()
    x_coll.where.return_value.stream.side_effect = _stream_factory(posts or [])
    c_coll = MagicMock()
    c_coll.where.return_value.stream.side_effect = _stream_factory(commentaries or [])

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


class TestStalledOpenPRs:
    def test_lists_open_prs_past_the_silence_threshold(self) -> None:
        md = survey_week(
            "2026-W21",
            client=_client(
                prs=[
                    _open_pr_dict(200, created_at=NOW - timedelta(days=20)),
                    _open_pr_dict(201, created_at=NOW - timedelta(days=2)),
                ]
            ),
            now=NOW,
        )
        assert "## Stalled open PRs" in md
        section = md.split("## Stalled open PRs")[1].split("\n## ")[0]
        assert "#200" in section
        # Two days of quiet is inside the observed normal range.
        assert "#201" not in section

    def test_row_carries_what_a_nudge_decision_needs(self) -> None:
        md = survey_week(
            "2026-W21",
            client=_client(
                prs=[
                    _open_pr_dict(
                        200,
                        title="fix: settle header missing on retry",
                        author="shuhei0866",
                        created_at=NOW - timedelta(days=40),
                        last_maintainer_activity_at=NOW - timedelta(days=15),
                        responders=["phdargen"],
                    )
                ]
            ),
            now=NOW,
        )
        section = md.split("## Stalled open PRs")[1].split("\n## ")[0]
        assert "#200" in section
        assert "fix: settle header missing on retry" in section
        assert "@shuhei0866" in section
        assert "15d" in section
        # Who last spoke, and when — the "new fact" a nudge needs.
        assert "@phdargen" in section
        assert "2026-05-10" in section
        assert "https://github.com/x402-foundation/x402/pull/200" in section

    def test_a_pr_nobody_ever_answered_says_so(self) -> None:
        md = survey_week(
            "2026-W21",
            client=_client(prs=[_open_pr_dict(200, created_at=NOW - timedelta(days=30))]),
            now=NOW,
        )
        section = md.split("## Stalled open PRs")[1].split("\n## ")[0]
        assert "no maintainer reaction" in section

    def test_merged_prs_never_appear(self) -> None:
        md = survey_week(
            "2026-W21",
            client=_client(prs=[_pr_dict(100, merged_at=datetime(2026, 1, 1, tzinfo=timezone.utc))]),
            now=NOW,
        )
        section = md.split("## Stalled open PRs")[1].split("\n## ")[0]
        assert "#100" not in section

    def test_threshold_is_overridable_from_the_caller(self) -> None:
        client_args = {"prs": [_open_pr_dict(200, created_at=NOW - timedelta(days=4))]}
        assert "#200" not in survey_week(
            "2026-W21", client=_client(**client_args), now=NOW
        ).split("## Stalled open PRs")[1].split("\n## ")[0]
        loosened = survey_week(
            "2026-W21", client=_client(**client_args), now=NOW, stalled_after_days=3
        )
        assert "#200" in loosened.split("## Stalled open PRs")[1].split("\n## ")[0]


class TestCrossSdkParityGaps:
    def test_lists_a_single_sdk_fix_with_no_counterpart(self) -> None:
        md = survey_week(
            "2026-W21",
            client=_client(
                prs=[
                    _open_pr_dict(
                        300,
                        title="fix: settle header missing on retry",
                        changed_paths=["python/x402/settle.py"],
                    )
                ]
            ),
            now=NOW,
        )
        assert "## Cross-SDK parity gaps" in md
        section = md.split("## Cross-SDK parity gaps")[1].split("\n## ")[0]
        assert "#300" in section
        assert "python" in section
        # Which SDKs to go look at, and what to read first.
        assert "typescript" in section and "go" in section
        assert "python/x402/settle.py" in section

    def test_a_fix_present_in_every_sdk_is_not_listed(self) -> None:
        md = survey_week(
            "2026-W21",
            client=_client(
                prs=[
                    _open_pr_dict(
                        300,
                        title="fix: settle header missing on retry",
                        changed_paths=["python/x402/settle.py"],
                    ),
                    _open_pr_dict(
                        301,
                        title="fix: settle header missing on retry",
                        changed_paths=["typescript/src/settle.ts"],
                    ),
                    _open_pr_dict(
                        302,
                        title="fix: settle header missing on retry",
                        changed_paths=["go/pkg/settle.go"],
                    ),
                ]
            ),
            now=NOW,
        )
        section = md.split("## Cross-SDK parity gaps")[1].split("\n## ")[0]
        assert "#300" not in section
        assert "No single-SDK fix" in section

    def test_rows_without_indexed_paths_are_reported_not_hidden(self) -> None:
        # An un-enriched index must not read as "no gaps this week".
        md = survey_week(
            "2026-W21",
            client=_client(prs=[_open_pr_dict(300, changed_paths=[])]),
            now=NOW,
        )
        section = md.split("## Cross-SDK parity gaps")[1].split("\n## ")[0]
        assert "no indexed file paths" in section
        assert "1 of 1" in section


class TestSnapshotScoutingCounts:
    def test_snapshot_counts_both_scouting_views(self) -> None:
        md = survey_week(
            "2026-W21",
            client=_client(
                prs=[
                    _open_pr_dict(
                        300,
                        title="fix: settle header missing on retry",
                        created_at=NOW - timedelta(days=30),
                        changed_paths=["python/x402/settle.py"],
                    )
                ]
            ),
            now=NOW,
        )
        snapshot = md.split("## Snapshot")[1].split("\n## ")[0]
        assert "1 stalled open PR(s)" in snapshot
        assert "1 cross-SDK parity gap(s)" in snapshot


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
