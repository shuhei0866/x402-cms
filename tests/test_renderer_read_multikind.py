"""Tests for the multi-kind PR reader and the issue reader.

`read_prs_by_kind` reads the same `source_data` collection as
`read_week` but keeps only the rows the indexer labels `active` / `new`
(those carry no `merged_at`, so they rehydrate as `PRRecord`). It sorts
on the timestamp the kind keys on. `read_issues_for_week` reads the
separate `issues` collection, most-discussed first.

The client is a MagicMock, as in `test_renderer_read`: the tests pin
the collection name and the in-memory sort without a live Firestore.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from code.renderers.digest import (
    COLLECTION,
    ISSUES_COLLECTION,
    read_issues_for_week,
    read_prs_by_kind,
)
from code.schemas.issue import IssueRecord
from code.schemas.pr import PRRecord

D1 = datetime(2026, 5, 5, tzinfo=timezone.utc)
D2 = datetime(2026, 5, 7, tzinfo=timezone.utc)
D3 = datetime(2026, 5, 9, tzinfo=timezone.utc)


def _client_returning(payloads: list[dict]) -> MagicMock:
    client = MagicMock()
    where_q = client.collection.return_value.where.return_value
    docs = []
    for p in payloads:
        d = MagicMock()
        d.to_dict.return_value = p
        docs.append(d)
    where_q.stream.return_value = iter(docs)
    return client


def _pr(
    number: int,
    *,
    kind: str,
    status: str = "open",
    updated_at: datetime | None = None,
    created_at: datetime | None = None,
) -> dict:
    return {
        "repo": "x402-foundation/x402",
        "pr_number": number,
        "title": f"PR {number}",
        "author": "someone",
        "url": f"https://github.com/x402-foundation/x402/pull/{number}",
        "week": "2026-W19",
        "status": status,
        "kind": kind,
        "merged_at": None,
        "updated_at": updated_at.isoformat() if updated_at else None,
        "created_at": created_at.isoformat() if created_at else None,
        "comments": 4,
        "labels": [],
    }


def _issue(number: int, *, comments: int, updated_at: datetime | None = None) -> dict:
    return {
        "repo": "x402-foundation/x402",
        "issue_number": number,
        "title": f"Issue {number}",
        "author": "someone",
        "url": f"https://github.com/x402-foundation/x402/issues/{number}",
        "week": "2026-W19",
        "state": "open",
        "kind": "active",
        "comments": comments,
        "created_at": None,
        "updated_at": updated_at.isoformat() if updated_at else None,
        "closed_at": None,
        "labels": [],
    }


class TestReadPrsByKind:
    def test_keeps_only_the_requested_kind(self) -> None:
        client = _client_returning(
            [
                _pr(1, kind="active", updated_at=D1),
                _pr(2, kind="new", created_at=D1),
                _pr(3, kind="active", updated_at=D2),
            ]
        )
        prs = read_prs_by_kind("2026-W19", "active", client=client)
        assert all(isinstance(p, PRRecord) for p in prs)
        assert {p.pr_number for p in prs} == {1, 3}
        client.collection.assert_called_once_with(COLLECTION)

    def test_active_sorted_by_updated_at_desc(self) -> None:
        client = _client_returning(
            [
                _pr(1, kind="active", updated_at=D1),
                _pr(2, kind="active", updated_at=D3),
                _pr(3, kind="active", updated_at=D2),
            ]
        )
        prs = read_prs_by_kind("2026-W19", "active", client=client)
        assert [p.pr_number for p in prs] == [2, 3, 1]

    def test_new_sorted_by_created_at_desc(self) -> None:
        client = _client_returning(
            [
                _pr(1, kind="new", created_at=D2),
                _pr(2, kind="new", created_at=D3),
            ]
        )
        prs = read_prs_by_kind("2026-W19", "new", client=client)
        assert [p.pr_number for p in prs] == [2, 1]

    def test_rows_without_kind_are_excluded(self) -> None:
        # A merged row (or a pre-multi-kind doc that lacks `kind`) must
        # never leak into the active / new lists.
        client = _client_returning(
            [
                {
                    "repo": "x402-foundation/x402",
                    "pr_number": 9,
                    "title": "merged",
                    "author": "a",
                    "url": "u",
                    "week": "2026-W19",
                }
            ]
        )
        assert read_prs_by_kind("2026-W19", "active", client=client) == []


class TestReadIssuesForWeek:
    def test_targets_issues_collection_and_rehydrates(self) -> None:
        client = _client_returning([_issue(50, comments=12, updated_at=D1)])
        issues = read_issues_for_week("2026-W19", client=client)
        assert len(issues) == 1
        assert isinstance(issues[0], IssueRecord)
        assert issues[0].issue_number == 50
        client.collection.assert_called_once_with(ISSUES_COLLECTION)

    def test_sorted_most_discussed_first(self) -> None:
        client = _client_returning(
            [
                _issue(1, comments=2, updated_at=D1),
                _issue(2, comments=9, updated_at=D1),
                _issue(3, comments=5, updated_at=D1),
            ]
        )
        issues = read_issues_for_week("2026-W19", client=client)
        assert [i.issue_number for i in issues] == [2, 3, 1]

    def test_empty_returns_empty(self) -> None:
        client = _client_returning([])
        assert read_issues_for_week("2026-W19", client=client) == []
