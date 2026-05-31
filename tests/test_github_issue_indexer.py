"""Tests for the active-issue indexer.

Issues surface a different signal from PRs (design discussion, RFC
drafts, bug reports), so they live in their own `issues` collection.
What we lock in:

- the Search query — `is:issue updated:WINDOW comments:>=N` with the
  inclusive `end - 1 day` upper bound;
- the PR filter: GitHub's `is:issue` search also returns PRs, and the
  indexer must drop any row carrying a `pull_request` block so it never
  duplicates the PR indexer's rows;
- the row mapping, including the `week` label from the run's window.
"""

from __future__ import annotations

from datetime import date

import httpx

from code.indexers.github_issue_indexer import (
    _is_pull_request,
    doc_id,
    fetch_active_issues,
)
from code.schemas.issue import IssueRecord

REPO = "x402-foundation/x402"
START = date(2026, 5, 4)
END = date(2026, 5, 11)  # exclusive; window upper bound is END - 1 day


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _issue_item(
    number: int,
    *,
    state: str = "open",
    comments: int = 6,
    login: str = "phdargen",
    labels: list[str] | None = None,
    is_pr: bool = False,
) -> dict:
    item = {
        "number": number,
        "title": f"Issue {number}",
        "user": {"login": login},
        "labels": [{"name": n} for n in (labels or [])],
        "html_url": f"https://github.com/{REPO}/issues/{number}",
        "state": state,
        "comments": comments,
        "created_at": "2026-05-04T00:00:00Z",
        "updated_at": "2026-05-07T00:00:00Z",
        "closed_at": None,
    }
    if is_pr:
        item["pull_request"] = {"url": "https://api.github.com/.../pulls/1"}
    return item


class TestIsPullRequest:
    def test_row_with_pull_request_block_is_a_pr(self) -> None:
        assert _is_pull_request({"pull_request": {"url": "..."}}) is True

    def test_row_without_pull_request_block_is_an_issue(self) -> None:
        assert _is_pull_request({"number": 1}) is False


class TestFetchActiveIssues:
    def test_issue_row_maps_and_query_is_correct(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["q"] = request.url.params.get("q")
            return httpx.Response(
                200,
                json={
                    "total_count": 1,
                    "items": [
                        _issue_item(50, comments=12, labels=["discussion"]),
                    ],
                },
            )

        with _client(handler) as client:
            issues = fetch_active_issues(
                REPO, START, END, min_comments=5, iso_week="2026-W19", http_client=client
            )

        assert len(issues) == 1
        issue = issues[0]
        assert issue.issue_number == 50
        assert issue.kind == "active"
        assert issue.state == "open"
        assert issue.comments == 12
        assert issue.week == "2026-W19"
        assert issue.author == "phdargen"
        assert issue.labels == ["discussion"]
        assert "search/issues" in captured["url"]
        assert captured["q"] == (
            f"repo:{REPO} is:issue updated:2026-05-04..2026-05-10 comments:>=5"
        )

    def test_pull_requests_are_filtered_out(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "total_count": 2,
                    "items": [
                        _issue_item(1),
                        _issue_item(2, is_pr=True),
                    ],
                },
            )

        with _client(handler) as client:
            issues = fetch_active_issues(
                REPO, START, END, min_comments=5, iso_week="2026-W19", http_client=client
            )
        assert [i.issue_number for i in issues] == [1]

    def test_empty_window_returns_empty(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"total_count": 0, "items": []})

        with _client(handler) as client:
            assert fetch_active_issues(REPO, START, END, http_client=client) == []


class TestDocId:
    def test_includes_week_so_cross_week_rows_do_not_collide(self) -> None:
        def _issue(week: str) -> IssueRecord:
            return IssueRecord(
                repo="x402-foundation/x402",
                issue_number=50,
                title="t",
                author="a",
                url="u",
                week=week,
                state="open",
                kind="active",
            )

        assert doc_id(_issue("2026-W21")) != doc_id(_issue("2026-W22"))
        assert doc_id(_issue("2026-W22")) == "x402-foundation__x402_50_2026-W22"
