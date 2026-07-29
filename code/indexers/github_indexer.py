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
documents in place. The document ID is `{repo_safe}_{pr_number}_{week}`
— the week is part of the key so a PR that stays active across weeks is
snapshotted per week rather than overwriting an earlier week's row. The
kind is not in the key, so a PR that surfaces under multiple kinds in
the same week converges on the row written last (the CLI orders `all`
as active → new → merged, so a merged-this-week PR ends up labelled
`kind=merged`).

After the search, an enrichment pass fills the two fields the Search
API does not carry but the survey's scouting views need: the paths a
PR touches (cross-SDK parity gap) and the last maintainer reaction on
it (stalled-PR list). It costs one REST call per PR for the files, plus
two more for each PR that is not merged yet. Pass `--no-enrich` to skip
it. Enrichment is best-effort: if GitHub starts refusing calls, the
remaining PRs keep their empty defaults and the run still writes.

The Search API is called unauthenticated by default (10 req/min,
ample for a weekly run). Set `GITHUB_TOKEN` or `GH_TOKEN` for the
30 req/min authenticated quota and to lift the 1000-result cap. The
enrichment pass draws on the ordinary REST quota instead — 60 req/hour
unauthenticated, which a busy week exhausts, so a token matters more
once enrichment is on.
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

FILES_URL = "https://api.github.com/repos/{repo}/pulls/{number}/files"
COMMENTS_URL = "https://api.github.com/repos/{repo}/issues/{number}/comments"
REVIEWS_URL = "https://api.github.com/repos/{repo}/pulls/{number}/reviews"
REST_PAGE_SIZE = 100
REST_MAX_PAGES = 3

MAINTAINER_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
"""GitHub's own answer to "does this person speak for the project?".

Every comment and review carries an `author_association`. `OWNER`,
`MEMBER` and `COLLABORATOR` all mean org membership or write access on
the repo; `CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR` and `NONE` do not. So
the indexer never needs a hand-maintained maintainer roster, and never
has to guess — which keeps the whole path mechanical.
"""

Kind = Literal["merged", "active", "new"]


class EnrichmentRefused(RuntimeError):
    """GitHub declined an enrichment call (rate limit, or repo gone).

    Raised so `enrich_prs` can stop the remaining per-PR calls in one
    place rather than hammering an endpoint that is already saying no.
    The rows keep their empty defaults; the survey views report how many
    rows lack indexed data instead of pretending the gap is real.
    """


def _api_headers() -> dict[str, str]:
    """Common headers for both the Search and the REST calls."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "x402-cms-indexer",
    }
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _parse_ts(value: str | None) -> datetime | None:
    """Parse a GitHub timestamp (`...Z`) into an aware `datetime`."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


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
    headers = _api_headers()

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
        merged_at = _parse_ts(pr_block.get("merged_at"))
        created_at = _parse_ts(item.get("created_at"))
        updated_at = _parse_ts(item.get("updated_at"))

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


def _get_pages(
    client: httpx.Client,
    url: str,
    headers: dict[str, str],
    *,
    max_pages: int = REST_MAX_PAGES,
) -> tuple[list[dict], bool]:
    """Read up to `max_pages` pages of a REST list endpoint.

    Returns the rows and whether the cap was hit — a full final page
    means "there may be more", so the flag over-reports rather than
    letting a caller mistake a prefix for the whole list.
    """
    rows: list[dict] = []
    for page in range(1, max_pages + 1):
        response = client.get(
            url,
            params={"per_page": REST_PAGE_SIZE, "page": page},
            headers=headers,
        )
        if response.status_code >= 400:
            raise EnrichmentRefused(f"{url} returned HTTP {response.status_code}")
        batch = response.json()
        if not isinstance(batch, list):
            raise EnrichmentRefused(f"{url} returned a non-list body")
        rows.extend(batch)
        if len(batch) < REST_PAGE_SIZE:
            return rows, False
    return rows, True


def fetch_changed_paths(
    repo: str,
    number: int,
    *,
    http_client: httpx.Client,
    headers: dict[str, str] | None = None,
) -> tuple[list[str], bool]:
    """Return the file paths a PR touches, and whether the list is cut off.

    Only the post-rename path is kept: the parity view asks "which SDK
    directory does this change live in", and for a renamed file that is
    where it landed, not where it came from.
    """
    rows, truncated = _get_pages(
        http_client, FILES_URL.format(repo=repo, number=number), headers or _api_headers()
    )
    return [row["filename"] for row in rows if row.get("filename")], truncated


def _is_maintainer_event(event: dict, pr_author: str) -> bool:
    """Is this comment/review a reaction *from the project* to the PR?

    Three exclusions, all mechanical. The PR's own author is dropped
    even when they are a maintainer — a maintainer replying under their
    own PR is not the project answering a contributor, and counting it
    would hide exactly the PRs nobody has looked at. Bots are dropped
    because a CI status comment is not a human deciding anything.
    Everyone else is judged by `author_association`.
    """
    user = event.get("user") or {}
    login = user.get("login") or ""
    if not login or login == pr_author:
        return False
    if user.get("type") == "Bot" or login.endswith("[bot]"):
        return False
    return (event.get("author_association") or "").upper() in MAINTAINER_ASSOCIATIONS


def fetch_maintainer_activity(
    repo: str,
    number: int,
    pr_author: str,
    *,
    http_client: httpx.Client,
    headers: dict[str, str] | None = None,
) -> tuple[datetime | None, list[str]]:
    """Return the newest maintainer reaction on a PR, and who reacted.

    Two endpoints cover what a maintainer can say on a PR in a way the
    API stamps with an association: issue comments (the conversation
    tab) and reviews (approve / request-changes / comment). `None` back
    means no maintainer has said anything yet — which is the state the
    stalled view most wants to surface, so it is a value, not an error.
    """
    headers = headers or _api_headers()
    reactions: list[tuple[datetime, str]] = []

    comments, _ = _get_pages(
        http_client, COMMENTS_URL.format(repo=repo, number=number), headers
    )
    for comment in comments:
        stamp = _parse_ts(comment.get("created_at"))
        if stamp and _is_maintainer_event(comment, pr_author):
            reactions.append((stamp, comment["user"]["login"]))

    reviews, _ = _get_pages(
        http_client, REVIEWS_URL.format(repo=repo, number=number), headers
    )
    for review in reviews:
        # A review still being drafted has no `submitted_at`; it is not
        # visible to the contributor either, so it is not a reaction.
        stamp = _parse_ts(review.get("submitted_at"))
        if stamp and _is_maintainer_event(review, pr_author):
            reactions.append((stamp, review["user"]["login"]))

    if not reactions:
        return None, []
    latest = max(stamp for stamp, _ in reactions)
    return latest, sorted({login for _, login in reactions})


def enrich_prs(
    prs: list[PRRecord],
    *,
    http_client: httpx.Client | None = None,
) -> int:
    """Fill `changed_paths` / maintainer-activity fields in place.

    Returns how many PRs were enriched. Every PR gets its file list (the
    parity view compares merged fixes across SDKs too); only PRs that
    have not merged get the two timeline calls, since a merged PR cannot
    be stalled.

    Best-effort by design: the first refusal from GitHub stops the pass
    and leaves the rest at their defaults, because the weekly job losing
    the whole search result to a rate limit would be a far worse trade
    than an incomplete enrichment the survey can report as incomplete.
    """
    if not prs:
        return 0

    headers = _api_headers()
    owns_client = http_client is None
    client = http_client or httpx.Client(timeout=30.0)
    enriched = 0
    try:
        for pr in prs:
            try:
                pr.changed_paths, pr.paths_truncated = fetch_changed_paths(
                    pr.repo, pr.pr_number, http_client=client, headers=headers
                )
                if pr.status != "merged":
                    (
                        pr.last_maintainer_activity_at,
                        pr.maintainer_responders,
                    ) = fetch_maintainer_activity(
                        pr.repo, pr.pr_number, pr.author, http_client=client, headers=headers
                    )
                enriched += 1
            except (EnrichmentRefused, httpx.HTTPError) as exc:
                print(
                    f"WARNING: enrichment stopped at PR #{pr.pr_number} ({exc}). "
                    f"{enriched}/{len(prs)} PR(s) carry paths and maintainer "
                    "activity; the rest are written without them. Set "
                    "GITHUB_TOKEN for the authenticated REST quota.",
                    file=sys.stderr,
                )
                break
    finally:
        if owns_client:
            client.close()
    return enriched


def doc_id(pr: PRRecord) -> str:
    """Firestore document ID for a PR — `{repo_safe}_{pr_number}_{week}`.

    The kind is left out so a PR that crosses kinds within the same
    week (active early in the week, merged on Friday) converges on a
    single row with the latest status, not two rivalling docs. The week
    is part of the key so a PR that stays active across weeks is
    snapshotted per week: without it a later week's run would rewrite
    an earlier week's row's `week` field and drop it from that week's
    digest (the readers filter by `week`).
    """
    repo_safe = pr.repo.replace("/", "__")
    return f"{repo_safe}_{pr.pr_number}_{pr.week}"


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
        "--no-enrich",
        action="store_true",
        help=(
            "Skip the per-PR REST pass that fills changed file paths and "
            "the last maintainer reaction. Saves one call per PR (three "
            "for unmerged ones) at the cost of leaving the survey's "
            "parity-gap and stalled-PR views without input."
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
        if not args.no_enrich and prs:
            enriched = enrich_prs(prs)
            print(
                f"Enriched {enriched}/{len(prs)} {kind} PR(s) with changed "
                "paths and maintainer activity.",
                file=sys.stderr,
            )
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
