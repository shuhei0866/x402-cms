"""GitHub indexer — fetch PRs from tracked x402 repositories.

Three Search-API qualifiers cover the things we want to track this
week:

- `merged` — `is:pr is:merged merged:WEEK`. The original behaviour;
  what landed.
- `active` — `is:pr -is:merged updated:WEEK comments:>=N`. Open or
  draft PRs that received discussion during the window.
- `new` — `is:pr -is:merged created:WEEK`. PRs opened this week,
  regardless of whether discussion has started.

Run with:

    uv run python -m code.indexers.github_indexer --kind merged --week 2026-W19
    uv run python -m code.indexers.github_indexer --kind active --week 2026-W19
    uv run python -m code.indexers.github_indexer --kind new    --week 2026-W19
    uv run python -m code.indexers.github_indexer --kind all    --week 2026-W19

Idempotent: re-running for the same week overwrites existing
documents in place. The document ID is `{repo_safe}_{pr_number}`, so
a PR that surfaces under multiple kinds in the same run ends up with
the row written last (the CLI orders `all` as active → new → merged,
so a merged-this-week PR ends up labelled `kind=merged`).

The Search API is called unauthenticated by default (10 req/min,
ample for a weekly run). Set `GITHUB_TOKEN` or `GH_TOKEN` for the
30 req/min authenticated quota and to lift the 1000-result cap.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from typing import Literal

import httpx

from code.schemas.pr import PRRecord, PRStatus
from code.utils.dates import parse_iso_week, resolve_target_week, week_of
from code.utils.firestore import build_client

DEFAULT_REPO = "x402-foundation/x402"
COLLECTION = "source_data"
SEARCH_URL = "https://api.github.com/search/issues"
SEARCH_PAGE_SIZE = 100
DEFAULT_MIN_COMMENTS = 5

Kind = Literal["merged", "active", "new"]


def _build_query(repo: str, kind: Kind, start: date, end: date, min_comments: int) -> str:
    """Compose the Search API `q` parameter for a given kind."""
    inclusive_end = (end - timedelta(days=1)).isoformat()
    window = f"{start.isoformat()}..{inclusive_end}"
    base = f"repo:{repo} is:pr"
    if kind == "merged":
        return f"{base} is:merged merged:{window}"
    if kind == "active":
        return f"{base} -is:merged updated:{window} comments:>={min_comments}"
    if kind == "new":
        return f"{base} -is:merged created:{window}"
    raise ValueError(f"unknown kind: {kind}")


def _status_for(item: dict, kind: Kind) -> PRStatus:
    """Derive the PR's current state from a Search API result row.

    Search items expose `state` (open/closed) and a top-level
    `draft: bool`. `pull_request.merged_at` distinguishes merged
    closes from plain closes when the `merged` kind would not have
    already isolated those.
    """
    if kind == "merged":
        return "merged"
    if item.get("draft"):
        return "draft"
    if item.get("state") == "closed":
        merged_at = (item.get("pull_request") or {}).get("merged_at")
        return "merged" if merged_at else "closed"
    return "open"


def fetch_prs(
    repo: str,
    kind: Kind,
    start: date,
    end: date,
    *,
    min_comments: int = DEFAULT_MIN_COMMENTS,
    http_client: httpx.Client | None = None,
    iso_week: str | None = None,
) -> list[PRRecord]:
    """Fetch PRs in [start, end) via the GitHub Search API.

    The `iso_week` argument seeds the `week` field for `active` rows,
    whose `updated_at` already lives inside the window (so the label
    matches the run); merged/new rows derive their label from the
    timestamp the kind keys on (`merged_at` / `created_at`).
    """
    query = _build_query(repo, kind, start, end, min_comments)
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
            f"WARNING: {total} '{kind}' PRs match the window but only the "
            f"first {SEARCH_PAGE_SIZE} are indexed; bump pagination if "
            f"weekly volume sustains this level.",
            file=sys.stderr,
        )

    fallback_week = iso_week or f"{start.isocalendar().year:04d}-W{start.isocalendar().week:02d}"
    prs: list[PRRecord] = []
    for item in data.get("items", []):
        pr_block = item.get("pull_request") or {}
        merged_at_str = pr_block.get("merged_at")
        merged_at = (
            datetime.fromisoformat(merged_at_str.replace("Z", "+00:00"))
            if merged_at_str
            else None
        )
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

        if kind == "merged":
            if not merged_at:
                continue
            week_label = week_of(merged_at)
        elif kind == "new":
            week_label = week_of(created_at) if created_at else fallback_week
        else:
            week_label = fallback_week

        prs.append(
            PRRecord(
                repo=repo,
                pr_number=item["number"],
                title=item["title"],
                author=item["user"]["login"],
                labels=[label["name"] for label in (item.get("labels") or [])],
                url=item["html_url"],
                week=week_label,
                status=_status_for(item, kind),
                kind=kind,
                merged_at=merged_at,
                updated_at=updated_at,
                created_at=created_at,
                comments=item.get("comments", 0),
            )
        )
    return prs


def doc_id(pr: PRRecord) -> str:
    """Firestore document ID for a PR — keyed for idempotency.

    The kind is intentionally left out: a PR that crosses kinds within
    the same week (e.g. active early in the week, merged on Friday)
    should converge on a single row with the latest status, not two
    rivalling docs.
    """
    repo_safe = pr.repo.replace("/", "__")
    return f"{repo_safe}_{pr.pr_number}"


def write_to_firestore(prs: list[PRRecord], project: str | None = None) -> int:
    """Write PRs to Firestore. Returns the number of documents written."""
    collection = build_client(project=project).collection(COLLECTION)
    for pr in prs:
        collection.document(doc_id(pr)).set(pr.model_dump(mode="json"))
    return len(prs)


# Order matters for `--kind all`: write the lighter kinds first so a
# PR that satisfies both (`active` early in the week then `merged` by
# Friday) ends up labelled `merged`.
ALL_KINDS: tuple[Kind, ...] = ("active", "new", "merged")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch PRs from a tracked repository into Firestore.",
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
        "--current",
        action="store_true",
        help=(
            "Target the in-progress ISO week instead of the previous "
            "one. Used by the daily scheduler to refresh the current "
            "week's digest; ignored when --week is given."
        ),
    )
    parser.add_argument(
        "--repo",
        default=DEFAULT_REPO,
        help=f"GitHub repository in 'owner/name' form (default: {DEFAULT_REPO}).",
    )
    parser.add_argument(
        "--kind",
        choices=("merged", "active", "new", "all"),
        default="merged",
        help=(
            "Which Search qualifier to run. 'all' runs active → new → "
            "merged in sequence so the merged kind wins when a PR "
            "qualifies for multiple."
        ),
    )
    parser.add_argument(
        "--min-comments",
        type=int,
        default=DEFAULT_MIN_COMMENTS,
        help=(
            "Comment-count floor for kind=active (default: "
            f"{DEFAULT_MIN_COMMENTS}). Ignored by other kinds."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and print results to stdout, but do not write to Firestore.",
    )
    args = parser.parse_args()

    week = resolve_target_week(args.week, args.current)
    start, end = parse_iso_week(week)
    inclusive_end = end - timedelta(days=1)

    kinds: tuple[Kind, ...] = ALL_KINDS if args.kind == "all" else (args.kind,)
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    grand_total = 0
    for kind in kinds:
        print(
            f"Fetching {kind} PRs from {args.repo} for {week} "
            f"({start.isoformat()}..{inclusive_end.isoformat()})",
            file=sys.stderr,
        )
        prs = fetch_prs(
            args.repo,
            kind,
            start,
            end,
            min_comments=args.min_comments,
            iso_week=week,
        )
        print(f"Fetched {len(prs)} {kind} PR(s).", file=sys.stderr)
        if args.dry_run:
            print(json.dumps([pr.model_dump(mode="json") for pr in prs], indent=2, default=str))
            continue
        written = write_to_firestore(prs, project=project)
        print(
            f"Wrote {written} {kind} document(s) to Firestore collection "
            f"'{COLLECTION}' (project: {project or 'ADC default'}).",
            file=sys.stderr,
        )
        grand_total += written

    if not args.dry_run and len(kinds) > 1:
        print(
            f"Total wrote {grand_total} document(s) across {len(kinds)} kinds.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
