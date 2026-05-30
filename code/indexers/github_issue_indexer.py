"""GitHub issue indexer — fetch active issues from tracked repositories.

Issues surface a different signal from PRs: design discussion, RFC
drafts, bug reports. The default Search qualifier is
`is:issue updated:WEEK comments:>=N` — only issues that received
meaningful discussion during the window, not every issue touched.

Run with:

    uv run python -m code.indexers.github_issue_indexer --week 2026-W19
    uv run python -m code.indexers.github_issue_indexer --week 2026-W19 --min-comments 3

Stored in the Firestore `issues` collection (separate from PRs), keyed
by `{repo_safe}_{issue_number}`. Idempotent under re-run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta

import httpx

from code.schemas.issue import IssueRecord, IssueState
from code.utils.dates import parse_iso_week, previous_iso_week
from code.utils.firestore import build_client

DEFAULT_REPO = "x402-foundation/x402"
COLLECTION = "issues"
SEARCH_URL = "https://api.github.com/search/issues"
SEARCH_PAGE_SIZE = 100
DEFAULT_MIN_COMMENTS = 5


def _is_pull_request(item: dict) -> bool:
    """GitHub's Search API returns PRs under `is:issue` as well.

    Items with a `pull_request` block are PRs; filter them out so the
    issue indexer never duplicates rows the PR indexer owns.
    """
    return "pull_request" in item


def fetch_active_issues(
    repo: str,
    start: date,
    end: date,
    *,
    min_comments: int = DEFAULT_MIN_COMMENTS,
    http_client: httpx.Client | None = None,
    iso_week: str | None = None,
) -> list[IssueRecord]:
    """Fetch issues touched in [start, end) with at least `min_comments`."""
    inclusive_end = (end - timedelta(days=1)).isoformat()
    query = (
        f"repo:{repo} is:issue "
        f"updated:{start.isoformat()}..{inclusive_end} "
        f"comments:>={min_comments}"
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "x402-cms-indexer",
    }
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    owns_client = http_client is None
    client = http_client or httpx.Client(timeout=30.0)
    try:
        response = client.get(
            SEARCH_URL,
            params={"q": query, "per_page": SEARCH_PAGE_SIZE, "page": 1},
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()
    finally:
        if owns_client:
            client.close()

    total = data.get("total_count", 0)
    if total > SEARCH_PAGE_SIZE:
        print(
            f"WARNING: {total} active issues match the window but only the "
            f"first {SEARCH_PAGE_SIZE} are indexed; bump pagination if "
            f"weekly volume sustains this level.",
            file=sys.stderr,
        )

    fallback_week = iso_week or f"{start.isocalendar().year:04d}-W{start.isocalendar().week:02d}"
    issues: list[IssueRecord] = []
    for item in data.get("items", []):
        if _is_pull_request(item):
            continue

        created_at_str = item.get("created_at")
        created_at = (
            datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            if created_at_str
            else None
        )
        updated_at_str = item.get("updated_at")
        updated_at = (
            datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
            if updated_at_str
            else None
        )
        closed_at_str = item.get("closed_at")
        closed_at = (
            datetime.fromisoformat(closed_at_str.replace("Z", "+00:00"))
            if closed_at_str
            else None
        )

        state: IssueState = "closed" if item.get("state") == "closed" else "open"

        issues.append(
            IssueRecord(
                repo=repo,
                issue_number=item["number"],
                title=item["title"],
                author=item["user"]["login"],
                labels=[label["name"] for label in (item.get("labels") or [])],
                url=item["html_url"],
                week=fallback_week,
                state=state,
                kind="active",
                comments=item.get("comments", 0),
                created_at=created_at,
                updated_at=updated_at,
                closed_at=closed_at,
            )
        )
    return issues


def doc_id(issue: IssueRecord) -> str:
    """Firestore document ID for an issue — keyed for idempotency."""
    repo_safe = issue.repo.replace("/", "__")
    return f"{repo_safe}_{issue.issue_number}"


def write_to_firestore(issues: list[IssueRecord], project: str | None = None) -> int:
    """Write issues to Firestore. Returns the number of documents written."""
    collection = build_client(project=project).collection(COLLECTION)
    for issue in issues:
        collection.document(doc_id(issue)).set(issue.model_dump(mode="json"))
    return len(issues)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch active issues from a tracked repository into Firestore.",
    )
    parser.add_argument(
        "--week",
        default=None,
        help=(
            "ISO week label, e.g. '2026-W19'. Defaults to the ISO week "
            "of (today - 7 days), i.e. the previous week."
        ),
    )
    parser.add_argument(
        "--repo",
        default=DEFAULT_REPO,
        help=f"GitHub repository in 'owner/name' form (default: {DEFAULT_REPO}).",
    )
    parser.add_argument(
        "--min-comments",
        type=int,
        default=DEFAULT_MIN_COMMENTS,
        help=f"Comment-count floor (default: {DEFAULT_MIN_COMMENTS}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and print results to stdout, but do not write to Firestore.",
    )
    args = parser.parse_args()

    week = args.week or previous_iso_week()
    start, end = parse_iso_week(week)
    inclusive_end = end - timedelta(days=1)
    print(
        f"Fetching active issues (comments>={args.min_comments}) from "
        f"{args.repo} for {week} "
        f"({start.isoformat()}..{inclusive_end.isoformat()})",
        file=sys.stderr,
    )

    issues = fetch_active_issues(
        args.repo,
        start,
        end,
        min_comments=args.min_comments,
        iso_week=week,
    )
    print(f"Fetched {len(issues)} active issue(s).", file=sys.stderr)

    if args.dry_run:
        print(json.dumps([i.model_dump(mode="json") for i in issues], indent=2, default=str))
        return 0

    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    written = write_to_firestore(issues, project=project)
    print(
        f"Wrote {written} document(s) to Firestore collection '{COLLECTION}' "
        f"(project: {project or 'ADC default'}).",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
