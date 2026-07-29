"""Tests for the multi-kind GitHub PR indexer.

The indexer fans the same repo into three Search-API qualifiers:
`merged` (what landed), `active` (open / draft PRs with live
discussion), and `new` (opened this week). What we lock in:

- the query each kind composes, with an inclusive `end - 1 day` upper
  bound on the window;
- the status derivation from a Search result row;
- the row mapping, including the `week` label each kind keys on
  (`merged_at` for merged, `created_at` for new, the run's window for
  active) and the merged-kind drop of rows that never merged.

The enrichment pass that follows the search has its own section: it
fills the two fields the survey's scouting views read, and its rules
about who counts as a maintainer and what happens when GitHub says no
are the load-bearing part.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import httpx

from code.indexers.github_indexer import (
    _build_query,
    _status_for,
    doc_id,
    enrich_prs,
    fetch_changed_paths,
    fetch_maintainer_activity,
    fetch_prs,
)
from code.schemas.pr import PRRecord

REPO = "x402-foundation/x402"
START = date(2026, 5, 4)
END = date(2026, 5, 11)  # exclusive; the window upper bound is END - 1 day


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _item(
    number: int,
    *,
    state: str = "open",
    merged_at: str | None = None,
    created_at: str = "2026-05-04T00:00:00Z",
    updated_at: str = "2026-05-06T00:00:00Z",
    comments: int = 2,
    draft: bool = False,
    login: str = "phdargen",
    labels: list[str] | None = None,
) -> dict:
    return {
        "number": number,
        "title": f"PR {number}",
        "user": {"login": login},
        "labels": [{"name": n} for n in (labels or [])],
        "html_url": f"https://github.com/{REPO}/pull/{number}",
        "state": state,
        "draft": draft,
        "comments": comments,
        "created_at": created_at,
        "updated_at": updated_at,
        "pull_request": {"merged_at": merged_at},
    }


def _responder(items: list[dict]):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["q"] = request.url.params.get("q")
        return httpx.Response(200, json={"total_count": len(items), "items": items})

    return handler, captured


class TestBuildQuery:
    def test_merged_uses_merged_qualifier_inclusive_window(self) -> None:
        q = _build_query(REPO, "merged", START, END, 5)
        assert q == f"repo:{REPO} is:pr is:merged merged:2026-05-04..2026-05-10"

    def test_active_excludes_merged_and_floors_comments(self) -> None:
        q = _build_query(REPO, "active", START, END, 5)
        assert q == (
            f"repo:{REPO} is:pr -is:merged "
            "updated:2026-05-04..2026-05-10 comments:>=5"
        )

    def test_new_is_unmerged_created_in_window(self) -> None:
        q = _build_query(REPO, "new", START, END, 5)
        assert q == f"repo:{REPO} is:pr -is:merged created:2026-05-04..2026-05-10"


class TestStatusFor:
    def test_merged_kind_is_always_merged(self) -> None:
        assert _status_for(_item(1, state="open"), "merged") == "merged"

    def test_draft_takes_precedence(self) -> None:
        assert _status_for(_item(1, draft=True), "active") == "draft"

    def test_closed_without_merge_is_closed(self) -> None:
        assert _status_for(_item(1, state="closed", merged_at=None), "active") == "closed"

    def test_closed_with_merge_is_merged(self) -> None:
        item = _item(1, state="closed", merged_at="2026-05-05T00:00:00Z")
        assert _status_for(item, "active") == "merged"

    def test_open_is_open(self) -> None:
        assert _status_for(_item(1, state="open"), "new") == "open"


class TestFetchPrs:
    def test_merged_row_maps_and_labels_by_merged_at(self) -> None:
        handler, captured = _responder(
            [
                _item(
                    1944,
                    state="closed",
                    merged_at="2026-05-05T12:00:00Z",
                    labels=["x402"],
                )
            ]
        )
        with _client(handler) as client:
            prs = fetch_prs(REPO, "merged", START, END, http_client=client)

        assert len(prs) == 1
        pr = prs[0]
        assert pr.pr_number == 1944
        assert pr.kind == "merged"
        assert pr.status == "merged"
        assert pr.merged_at is not None
        assert pr.week == "2026-W19"
        assert pr.author == "phdargen"
        assert pr.labels == ["x402"]
        assert "search/issues" in captured["url"]
        assert captured["q"] == f"repo:{REPO} is:pr is:merged merged:2026-05-04..2026-05-10"

    def test_merged_kind_skips_rows_that_never_merged(self) -> None:
        handler, _ = _responder([_item(1, state="open", merged_at=None)])
        with _client(handler) as client:
            prs = fetch_prs(REPO, "merged", START, END, http_client=client)
        assert prs == []

    def test_active_row_is_open_and_labelled_with_window_week(self) -> None:
        # An active PR can have been created long before the window;
        # its `week` comes from the run's `iso_week`, not `created_at`.
        handler, captured = _responder(
            [
                _item(
                    2,
                    state="open",
                    created_at="2026-04-01T00:00:00Z",
                    updated_at="2026-05-07T00:00:00Z",
                    comments=7,
                )
            ]
        )
        with _client(handler) as client:
            prs = fetch_prs(
                REPO, "active", START, END, iso_week="2026-W19", http_client=client
            )

        assert len(prs) == 1
        assert prs[0].kind == "active"
        assert prs[0].status == "open"
        assert prs[0].merged_at is None
        assert prs[0].comments == 7
        assert prs[0].week == "2026-W19"

    def test_new_row_labelled_by_created_at(self) -> None:
        handler, _ = _responder(
            [_item(3, state="open", created_at="2026-05-06T00:00:00Z")]
        )
        with _client(handler) as client:
            prs = fetch_prs(
                REPO, "new", START, END, iso_week="2026-W19", http_client=client
            )
        assert prs[0].kind == "new"
        assert prs[0].week == "2026-W19"
        assert prs[0].created_at is not None

    def test_empty_window_returns_empty(self) -> None:
        handler, _ = _responder([])
        with _client(handler) as client:
            assert fetch_prs(REPO, "new", START, END, http_client=client) == []


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


def _rest_router(
    *,
    files: list[dict] | None = None,
    comments: list[dict] | None = None,
    reviews: list[dict] | None = None,
    status: int = 200,
):
    """Route the three enrichment endpoints off one mock transport."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen.append(path)
        if status != 200:
            return httpx.Response(status, json={"message": "nope"})
        if path.endswith("/files"):
            body = files or []
        elif path.endswith("/comments"):
            body = comments or []
        else:
            body = reviews or []
        return httpx.Response(200, json=body)

    return handler, seen


def _pr_record(number: int = 1, *, status: str = "open", author: str = "shuhei0866") -> PRRecord:
    return PRRecord(
        repo=REPO,
        pr_number=number,
        title=f"fix: thing {number}",
        author=author,
        url=f"https://github.com/{REPO}/pull/{number}",
        week="2026-W19",
        status=status,
        kind="merged" if status == "merged" else "active",
    )


class TestFetchChangedPaths:
    def test_returns_the_touched_paths(self) -> None:
        handler, _ = _rest_router(
            files=[{"filename": "python/x402/settle.py"}, {"filename": "README.md"}]
        )
        with _client(handler) as client:
            paths, truncated = fetch_changed_paths(REPO, 42, http_client=client)
        assert paths == ["python/x402/settle.py", "README.md"]
        assert truncated is False

    def test_a_short_page_means_the_list_is_complete(self) -> None:
        handler, seen = _rest_router(files=[{"filename": "go/pkg/x.go"}])
        with _client(handler) as client:
            _, truncated = fetch_changed_paths(REPO, 42, http_client=client)
        # One page came back short, so no second request was made.
        assert len(seen) == 1
        assert truncated is False


class TestFetchMaintainerActivity:
    def test_newest_maintainer_reaction_across_comments_and_reviews(self) -> None:
        handler, _ = _rest_router(
            comments=[_comment("phdargen", "MEMBER", "2026-05-05T10:00:00Z")],
            reviews=[_review("CarsonRoscoe", "COLLABORATOR", "2026-05-07T09:00:00Z")],
        )
        with _client(handler) as client:
            last, responders = fetch_maintainer_activity(
                REPO, 42, "shuhei0866", http_client=client
            )
        assert last == datetime(2026, 5, 7, 9, 0, tzinfo=timezone.utc)
        assert responders == ["CarsonRoscoe", "phdargen"]

    def test_outside_contributors_do_not_count(self) -> None:
        handler, _ = _rest_router(
            comments=[
                _comment("randomdev", "CONTRIBUTOR", "2026-05-05T10:00:00Z"),
                _comment("newcomer", "NONE", "2026-05-06T10:00:00Z"),
            ]
        )
        with _client(handler) as client:
            last, responders = fetch_maintainer_activity(
                REPO, 42, "shuhei0866", http_client=client
            )
        assert last is None
        assert responders == []

    def test_the_pr_author_never_counts_even_when_a_maintainer(self) -> None:
        # A maintainer talking under their own PR is not the project
        # answering a contributor — counting it would hide exactly the
        # PRs nobody has looked at.
        handler, _ = _rest_router(
            comments=[_comment("phdargen", "MEMBER", "2026-05-05T10:00:00Z")]
        )
        with _client(handler) as client:
            last, _ = fetch_maintainer_activity(REPO, 42, "phdargen", http_client=client)
        assert last is None

    def test_bots_do_not_count(self) -> None:
        handler, _ = _rest_router(
            comments=[
                _comment(
                    "github-actions[bot]",
                    "COLLABORATOR",
                    "2026-05-05T10:00:00Z",
                    user_type="Bot",
                )
            ]
        )
        with _client(handler) as client:
            last, _ = fetch_maintainer_activity(REPO, 42, "shuhei0866", http_client=client)
        assert last is None

    def test_a_pending_review_is_not_a_reaction(self) -> None:
        # No `submitted_at` means the review is still a draft, invisible
        # to the contributor.
        handler, _ = _rest_router(reviews=[_review("phdargen", "MEMBER", None)])
        with _client(handler) as client:
            last, _ = fetch_maintainer_activity(REPO, 42, "shuhei0866", http_client=client)
        assert last is None

    def test_no_reaction_yet_is_a_value_not_an_error(self) -> None:
        handler, _ = _rest_router()
        with _client(handler) as client:
            assert fetch_maintainer_activity(REPO, 42, "shuhei0866", http_client=client) == (
                None,
                [],
            )


class TestEnrichPrs:
    def test_fills_paths_and_activity_on_an_open_pr(self) -> None:
        handler, seen = _rest_router(
            files=[{"filename": "python/x402/settle.py"}],
            comments=[_comment("phdargen", "MEMBER", "2026-05-05T10:00:00Z")],
        )
        prs = [_pr_record(1, status="open")]
        with _client(handler) as client:
            assert enrich_prs(prs, http_client=client) == 1

        assert prs[0].changed_paths == ["python/x402/settle.py"]
        assert prs[0].last_maintainer_activity_at == datetime(
            2026, 5, 5, 10, 0, tzinfo=timezone.utc
        )
        assert prs[0].maintainer_responders == ["phdargen"]
        assert len(seen) == 3  # files + comments + reviews

    def test_merged_rows_only_pay_for_the_file_list(self) -> None:
        # A merged PR cannot be stalled, so the two timeline calls buy
        # nothing; the parity view still needs its paths.
        handler, seen = _rest_router(files=[{"filename": "go/pkg/x.go"}])
        prs = [_pr_record(1, status="merged")]
        with _client(handler) as client:
            enrich_prs(prs, http_client=client)

        assert prs[0].changed_paths == ["go/pkg/x.go"]
        assert prs[0].last_maintainer_activity_at is None
        assert len(seen) == 1

    def test_a_refusal_stops_the_pass_without_failing_the_run(self) -> None:
        # Losing a whole week's search result to a rate limit would cost
        # far more than an enrichment the survey can report as partial.
        handler, _ = _rest_router(status=403)
        prs = [_pr_record(1), _pr_record(2)]
        with _client(handler) as client:
            assert enrich_prs(prs, http_client=client) == 0
        assert all(not pr.changed_paths for pr in prs)

    def test_empty_input_makes_no_calls(self) -> None:
        handler, seen = _rest_router()
        with _client(handler) as client:
            assert enrich_prs([], http_client=client) == 0
        assert seen == []


class TestDocId:
    @staticmethod
    def _pr(week: str, *, number: int = 1234, kind: str = "active") -> PRRecord:
        return PRRecord(
            repo="x402-foundation/x402",
            pr_number=number,
            title="t",
            author="a",
            url="u",
            week=week,
            status="open",
            kind=kind,
        )

    def test_includes_week_so_cross_week_rows_do_not_collide(self) -> None:
        # A PR active across two weeks lands in two docs, one per week,
        # so a later week's run never overwrites the earlier week's row
        # (which the readers filter by `week`).
        w21 = doc_id(self._pr("2026-W21"))
        w22 = doc_id(self._pr("2026-W22"))
        assert w21 != w22
        assert w21 == "x402-foundation__x402_1234_2026-W21"
        assert w22.endswith("_2026-W22")

    def test_same_pr_same_week_converges_regardless_of_kind(self) -> None:
        # Kind is not in the id: active / new / merged of the same PR in
        # the same week share one doc (merged wins via write order).
        assert doc_id(self._pr("2026-W22", number=9, kind="active")) == doc_id(
            self._pr("2026-W22", number=9, kind="merged")
        )
