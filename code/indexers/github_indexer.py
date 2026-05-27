"""GitHub indexer — fetch merged PRs from tracked x402 repositories.

Phase 1 / M1.2 scope: fetch merged pull requests from
`x402-foundation/x402` within an ISO-week window via the GitHub
Search API and write them to the Firestore `source_data` collection.

Run with:

    uv run python -m code.indexers.github_indexer --week 2026-W19

`--week` is optional; without it the indexer targets the previous ISO
week (today - 7 days), which is what a Monday-morning Cloud Scheduler
run wants — index the week that just ended.

Idempotent: re-running for the same week overwrites existing documents
in place. The document ID is `{repo_safe}_{pr_number}` where
`repo_safe` replaces `/` with `__` so it is a valid Firestore key.

The Search API is called unauthenticated by default (10 req/min, ample
for a weekly run). Set `GITHUB_TOKEN` or `GH_TOKEN` for the 30 req/min
authenticated quota and to lift the 1000-result cap.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta

import httpx

from code.schemas.pr import MergedPR
from code.utils.dates import parse_iso_week, previous_iso_week
from code.utils.firestore import build_client

DEFAULT_REPO = "x402-foundation/x402"
COLLECTION = "source_data"
SEARCH_URL = "https://api.github.com/search/issues"
SEARCH_PAGE_SIZE = 100  # GitHub Search API per-page maximum.


def fetch_merged_prs(
    repo: str,
    start: date,
    end: date,
    http_client: httpx.Client | None = None,
) -> list[MergedPR]:
    """Fetch merged PRs in [start, end) via the GitHub Search API.

    Uses the `merged:YYYY-MM-DD..YYYY-MM-DD` qualifier with an inclusive
    upper bound (`end - 1 day`). Auth optional via `GITHUB_TOKEN` /
    `GH_TOKEN`. Caps at one page of `SEARCH_PAGE_SIZE` results and
    emits a stderr warning if the window has more.
    """
    inclusive_end = end - timedelta(days=1)
    query = (
        f"repo:{repo} is:pr is:merged "
        f"merged:{start.isoformat()}..{inclusive_end.isoformat()}"
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
            f"WARNING: {total} merged PRs match the window but only the "
            f"first {SEARCH_PAGE_SIZE} are indexed; bump pagination if "
            f"weekly volume sustains this level.",
            file=sys.stderr,
        )

    prs: list[MergedPR] = []
    for item in data.get("items", []):
        pr_block = item.get("pull_request") or {}
        merged_at_str = pr_block.get("merged_at")
        if not merged_at_str:
            continue
        merged_at = datetime.fromisoformat(merged_at_str.replace("Z", "+00:00"))
        iso_year, iso_week, _ = merged_at.date().isocalendar()
        prs.append(
            MergedPR(
                repo=repo,
                pr_number=item["number"],
                title=item["title"],
                merged_at=merged_at,
                author=item["user"]["login"],
                labels=[label["name"] for label in (item.get("labels") or [])],
                url=item["html_url"],
                week=f"{iso_year:04d}-W{iso_week:02d}",
            )
        )
    return prs


def doc_id(pr: MergedPR) -> str:
    """Firestore document ID for a merged PR — keyed for idempotency."""
    repo_safe = pr.repo.replace("/", "__")
    return f"{repo_safe}_{pr.pr_number}"


def write_to_firestore(prs: list[MergedPR], project: str | None = None) -> int:
    """Write merged PRs to Firestore. Returns the number of documents written."""
    collection = build_client(project=project).collection(COLLECTION)
    for pr in prs:
        collection.document(doc_id(pr)).set(pr.model_dump(mode="json"))
    return len(prs)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch merged PRs from a tracked repository into Firestore.",
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
        "--dry-run",
        action="store_true",
        help="Fetch and print results to stdout, but do not write to Firestore.",
    )
    args = parser.parse_args()

    week = args.week or previous_iso_week()
    start, end = parse_iso_week(week)
    inclusive_end = end - timedelta(days=1)
    print(
        f"Fetching merged PRs from {args.repo} for {week} "
        f"({start.isoformat()}..{inclusive_end.isoformat()})",
        file=sys.stderr,
    )

    prs = fetch_merged_prs(args.repo, start, end)
    print(f"Fetched {len(prs)} merged PR(s).", file=sys.stderr)

    if args.dry_run:
        print(json.dumps([pr.model_dump(mode="json") for pr in prs], indent=2, default=str))
        return 0

    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    written = write_to_firestore(prs, project=project)
    print(
        f"Wrote {written} document(s) to Firestore collection '{COLLECTION}' "
        f"(project: {project or 'ADC default'}).",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
