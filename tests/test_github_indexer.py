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
"""

from __future__ import annotations

from datetime import date

import httpx

from code.indexers.github_indexer import (
    ALL_KINDS,
    _build_query,
    _status_for,
    doc_id,
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

    def test_open_snapshots_everything_currently_open_without_window(self) -> None:
        # No date window: the stalled-PR view needs quiet PRs opened
        # long before the week, which `active` / `new` never match.
        q = _build_query(REPO, "open", START, END, 5)
        assert q == f"repo:{REPO} is:pr is:open"


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

    def test_open_row_labelled_with_run_week_regardless_of_age(self) -> None:
        # The open snapshot has no window; a PR opened months ago is
        # bucketed into the week the run targets.
        handler, captured = _responder(
            [_item(7, state="open", created_at="2026-03-01T00:00:00Z")]
        )
        with _client(handler) as client:
            prs = fetch_prs(
                REPO, "open", START, END, iso_week="2026-W19", http_client=client
            )
        assert len(prs) == 1
        assert prs[0].kind == "open"
        assert prs[0].status == "open"
        assert prs[0].week == "2026-W19"
        assert captured["q"] == f"repo:{REPO} is:pr is:open"

    def test_open_kind_keeps_draft_status(self) -> None:
        handler, _ = _responder([_item(8, state="open", draft=True)])
        with _client(handler) as client:
            prs = fetch_prs(
                REPO, "open", START, END, iso_week="2026-W19", http_client=client
            )
        assert prs[0].status == "draft"

    def test_empty_window_returns_empty(self) -> None:
        handler, _ = _responder([])
        with _client(handler) as client:
            assert fetch_prs(REPO, "new", START, END, http_client=client) == []


class TestAllKindsOrder:
    def test_open_runs_first_so_specific_kinds_win_doc_collisions(self) -> None:
        # Kind is not in the doc id, so within one `--kind all` run the
        # write order decides the surviving label: the broad open
        # snapshot first, then active / new / merged relabel the rows
        # they also match.
        assert ALL_KINDS == ("open", "active", "new", "merged")


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
