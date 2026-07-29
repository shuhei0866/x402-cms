"""Tests for the per-PR enrichment pass.

`enrich_prs` fills `touched_paths` / `last_maintainer_activity_at` /
`enriched_at` from the core REST API. What we lock in:

- which endpoints are hit for which row status (merged rows skip the
  activity endpoints);
- the mechanical "maintainer response" rule — association OWNER /
  MEMBER / COLLABORATOR, never the PR author, never a bot — and the
  timestamp fields it keys on (comment `created_at`, review
  `submitted_at`, PENDING reviews skipped);
- the cache sharing across kinds, the per-PR failure degradation, and
  the full-page pagination follow-up.

The GitHub API is a `httpx.MockTransport` routing by URL path, as in
`test_github_indexer`.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from code.indexers.github_enrichment import PAGE_SIZE, enrich_prs
from code.schemas.pr import PRRecord

REPO = "x402-foundation/x402"
NOW = datetime(2026, 5, 26, 9, 0, tzinfo=timezone.utc)


def _pr(
    number: int,
    *,
    status: str = "open",
    kind: str = "open",
    author: str = "extdev",
) -> PRRecord:
    return PRRecord(
        repo=REPO,
        pr_number=number,
        title=f"PR {number}",
        author=author,
        url=f"https://github.com/{REPO}/pull/{number}",
        week="2026-W21",
        status=status,
        kind=kind,
    )


def _comment(
    login: str,
    association: str,
    created_at: str,
    *,
    user_type: str = "User",
) -> dict:
    return {
        "user": {"login": login, "type": user_type},
        "author_association": association,
        "created_at": created_at,
    }


def _review(
    login: str,
    association: str,
    submitted_at: str | None,
    *,
    user_type: str = "User",
) -> dict:
    return {
        "user": {"login": login, "type": user_type},
        "author_association": association,
        "submitted_at": submitted_at,
    }


class _FakeGitHub:
    """Routes /repos/{o}/{r}/{pulls|issues}/{n}/{files|comments|reviews}."""

    def __init__(self) -> None:
        self.files: dict[int, list[dict]] = {}
        self.comments: dict[int, list[dict]] = {}
        self.reviews: dict[int, list[dict]] = {}
        self.fail_numbers: set[int] = set()
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append(path)
        parts = path.strip("/").split("/")
        number = int(parts[4])
        if number in self.fail_numbers:
            return httpx.Response(500, json={"message": "boom"})
        if parts[3] == "pulls" and parts[5] == "files":
            rows = self.files.get(number, [])
        elif parts[3] == "issues" and parts[5] == "comments":
            rows = self.comments.get(number, [])
        elif parts[3] == "pulls" and parts[5] == "reviews":
            rows = self.reviews.get(number, [])
        else:
            return httpx.Response(404, json={"message": "no route"})
        page = int(request.url.params.get("page", "1"))
        per_page = int(request.url.params.get("per_page", str(PAGE_SIZE)))
        start = (page - 1) * per_page
        return httpx.Response(200, json=rows[start : start + per_page])

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


class TestEnrichOpenRows:
    def test_open_row_gets_paths_activity_and_stamp(self) -> None:
        gh = _FakeGitHub()
        gh.files[1] = [
            {"filename": "python/x402/verify.py"},
            {"filename": "python/tests/test_verify.py"},
        ]
        gh.comments[1] = [
            _comment("maintainer-a", "MEMBER", "2026-05-10T00:00:00Z"),
        ]
        gh.reviews[1] = [
            _review("maintainer-b", "OWNER", "2026-05-12T00:00:00Z"),
        ]
        with gh.client() as client:
            [row] = enrich_prs([_pr(1)], http_client=client, now=NOW)

        assert row.touched_paths == [
            "python/x402/verify.py",
            "python/tests/test_verify.py",
        ]
        # the review is newer than the comment; the max wins
        assert row.last_maintainer_activity_at == datetime(
            2026, 5, 12, tzinfo=timezone.utc
        )
        assert row.enriched_at == NOW

    def test_no_qualifying_activity_is_none_but_still_stamped(self) -> None:
        # `None` + `enriched_at` set is the "no maintainer has ever
        # responded" signal the stalled view keys on.
        gh = _FakeGitHub()
        gh.comments[1] = [
            _comment("passerby", "CONTRIBUTOR", "2026-05-10T00:00:00Z"),
        ]
        with gh.client() as client:
            [row] = enrich_prs([_pr(1)], http_client=client, now=NOW)
        assert row.last_maintainer_activity_at is None
        assert row.enriched_at == NOW


class TestMaintainerRule:
    def test_author_bots_and_non_maintainers_do_not_count(self) -> None:
        gh = _FakeGitHub()
        gh.comments[1] = [
            # the PR author is a MEMBER, but their own comment is not a response
            _comment("extdev", "MEMBER", "2026-05-20T00:00:00Z"),
            _comment("github-actions[bot]", "MEMBER", "2026-05-19T00:00:00Z"),
            _comment("some-app", "MEMBER", "2026-05-18T00:00:00Z", user_type="Bot"),
            _comment("passerby", "NONE", "2026-05-17T00:00:00Z"),
            _comment("collab", "COLLABORATOR", "2026-05-01T00:00:00Z"),
        ]
        with gh.client() as client:
            [row] = enrich_prs([_pr(1, author="extdev")], http_client=client, now=NOW)
        assert row.last_maintainer_activity_at == datetime(
            2026, 5, 1, tzinfo=timezone.utc
        )

    def test_pending_review_without_submitted_at_is_skipped(self) -> None:
        gh = _FakeGitHub()
        gh.reviews[1] = [_review("maintainer-a", "MEMBER", None)]
        with gh.client() as client:
            [row] = enrich_prs([_pr(1)], http_client=client, now=NOW)
        assert row.last_maintainer_activity_at is None


class TestRequestEconomy:
    def test_merged_rows_skip_activity_endpoints(self) -> None:
        gh = _FakeGitHub()
        gh.files[2] = [{"filename": "typescript/packages/x402/src/verify.ts"}]
        with gh.client() as client:
            [row] = enrich_prs(
                [_pr(2, status="merged", kind="merged")], http_client=client, now=NOW
            )
        assert row.touched_paths == ["typescript/packages/x402/src/verify.ts"]
        assert row.last_maintainer_activity_at is None
        assert row.enriched_at == NOW
        assert not any("/comments" in p or "/reviews" in p for p in gh.requests)

    def test_shared_cache_dedupes_requests_across_kinds(self) -> None:
        gh = _FakeGitHub()
        gh.files[3] = [{"filename": "go/pkg/client.go"}]
        cache: dict = {}
        with gh.client() as client:
            [first] = enrich_prs(
                [_pr(3, kind="open")], http_client=client, cache=cache, now=NOW
            )
            [second] = enrich_prs(
                [_pr(3, kind="active")], http_client=client, cache=cache, now=NOW
            )
        files_hits = [p for p in gh.requests if p.endswith("/files")]
        comments_hits = [p for p in gh.requests if p.endswith("/comments")]
        assert len(files_hits) == 1
        assert len(comments_hits) == 1
        assert first.touched_paths == second.touched_paths == ["go/pkg/client.go"]

    def test_pagination_follows_full_pages(self) -> None:
        gh = _FakeGitHub()
        gh.files[4] = [
            {"filename": f"python/x402/mod_{i}.py"} for i in range(PAGE_SIZE + 3)
        ]
        with gh.client() as client:
            [row] = enrich_prs([_pr(4, status="merged")], http_client=client, now=NOW)
        assert len(row.touched_paths) == PAGE_SIZE + 3


class TestFailureDegradation:
    def test_one_failing_pr_degrades_only_that_row(self) -> None:
        gh = _FakeGitHub()
        gh.fail_numbers.add(5)
        gh.files[6] = [{"filename": "python/x402/facilitator.py"}]
        with gh.client() as client:
            rows = enrich_prs([_pr(5), _pr(6)], http_client=client, now=NOW)
        failed, ok = rows
        assert failed.pr_number == 5
        assert failed.enriched_at is None
        assert failed.touched_paths == []
        assert ok.pr_number == 6
        assert ok.enriched_at == NOW
        assert ok.touched_paths == ["python/x402/facilitator.py"]
