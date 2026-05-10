"""GitHub indexer — fetch merged PRs from tracked x402 repositories.

Phase 1 / M1.2 scope: fetch merged pull requests from
`x402-foundation/x402` within an ISO-week window via the `gh` CLI and
write them to the Firestore `source_data` collection.

Run with:

    uv run python -m code.indexers.github_indexer --week 2026-W19

Idempotent: re-running for the same week overwrites existing documents
in place. The document ID is `{repo_safe}_{pr_number}` where
`repo_safe` replaces `/` with `__` so it is a valid Firestore key.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta

from google.cloud import firestore

from code.schemas.pr import MergedPR

DEFAULT_REPO = "x402-foundation/x402"
COLLECTION = "source_data"
GH_FETCH_LIMIT = 200


def parse_iso_week(week: str) -> tuple[date, date]:
    """Return [start, end) date bounds for an ISO week label like '2026-W19'.

    Start is the Monday of that ISO week; end is the following Monday
    (exclusive), so callers can build `gh` search ranges with
    `end - 1 day` as the inclusive upper bound.
    """
    year_str, week_str = week.split("-W")
    start = date.fromisocalendar(int(year_str), int(week_str), 1)
    end = start + timedelta(days=7)
    return start, end


def fetch_merged_prs(repo: str, start: date, end: date) -> list[MergedPR]:
    """Fetch merged PRs in [start, end) using the `gh` CLI.

    Uses the `merged:YYYY-MM-DD..YYYY-MM-DD` qualifier with an inclusive
    upper bound (`end - 1 day`).
    """
    inclusive_end = end - timedelta(days=1)
    search = f"merged:{start.isoformat()}..{inclusive_end.isoformat()}"

    cmd = [
        "gh",
        "pr",
        "list",
        "-R",
        repo,
        "--state",
        "merged",
        "--search",
        search,
        "--json",
        "number,title,mergedAt,author,labels,url",
        "--limit",
        str(GH_FETCH_LIMIT),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    raw = json.loads(result.stdout)

    prs: list[MergedPR] = []
    for item in raw:
        merged_at = datetime.fromisoformat(item["mergedAt"].replace("Z", "+00:00"))
        iso_year, iso_week, _ = merged_at.date().isocalendar()
        prs.append(
            MergedPR(
                repo=repo,
                pr_number=item["number"],
                title=item["title"],
                merged_at=merged_at,
                author=item["author"]["login"],
                labels=[label["name"] for label in (item.get("labels") or [])],
                url=item["url"],
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
    client = firestore.Client(project=project) if project else firestore.Client()
    collection = client.collection(COLLECTION)
    for pr in prs:
        collection.document(doc_id(pr)).set(pr.model_dump(mode="json"))
    return len(prs)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch merged PRs from a tracked repository into Firestore.",
    )
    parser.add_argument(
        "--week",
        required=True,
        help="ISO week label, e.g. '2026-W19'.",
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

    start, end = parse_iso_week(args.week)
    inclusive_end = end - timedelta(days=1)
    print(
        f"Fetching merged PRs from {args.repo} for {args.week} "
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
