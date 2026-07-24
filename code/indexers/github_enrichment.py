"""Per-PR enrichment — touched paths and the last maintainer response.

The Search API rows `github_indexer` fetches say nothing about which
files a PR touches or when a maintainer last engaged with it. The two
survey views added for issue #17 need exactly that: the cross-SDK
parity view classifies fixes by the SDK directory their paths fall
under, and the stalled-PR view measures how long an open PR has been
waiting for a maintainer. So after each Search pass the indexer calls
`enrich_prs`, which fills three `PRRecord` fields via the core REST
API:

- ``GET /repos/{repo}/pulls/{n}/files``    -> ``touched_paths`` (all rows)
- ``GET /repos/{repo}/issues/{n}/comments``
  + ``GET /repos/{repo}/pulls/{n}/reviews`` -> ``last_maintainer_activity_at``
  (open / draft rows only — a merged row's silence is moot)

"Maintainer response" is a mechanical rule, not a judgment: an issue
comment or a submitted review whose `author_association` is OWNER,
MEMBER, or COLLABORATOR, authored by neither the PR author nor a bot.
`author_association` ships inside every comment/review row, so no
extra org-membership lookups (or admin-scoped tokens) are needed.

`enriched_at` is stamped on every successfully enriched row so readers
can tell "enrichment ran and no maintainer has responded" (activity
None, `enriched_at` set) from "the indexer never checked" (both None).

Cost: 1-3 core-API requests per PR. The unauthenticated core quota
(60/hr) is too small for a weekly batch — set GITHUB_TOKEN / GH_TOKEN
(5000/hr), or pass `--no-enrich` to the indexer CLI.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import httpx

from code.schemas.pr import PRRecord

API_ROOT = "https://api.github.com"
PAGE_SIZE = 100
# Pages fetched per list endpoint before warning and stopping — 300
# files / comments / reviews covers any realistic x402 PR; the warning
# keeps a silent truncation from masquerading as full coverage.
MAX_PAGES = 3
MAINTAINER_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})


def request_headers() -> dict[str, str]:
    """Standard GitHub API headers; bearer token when the env has one."""
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
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _paged(client: httpx.Client, url: str, headers: dict[str, str]) -> list[dict]:
    """Fetch up to MAX_PAGES pages of a list endpoint, warning on truncation."""
    items: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        response = client.get(
            url, params={"per_page": PAGE_SIZE, "page": page}, headers=headers
        )
        response.raise_for_status()
        batch = response.json()
        items.extend(batch)
        if len(batch) < PAGE_SIZE:
            return items
    print(
        f"WARNING: {url} still returned full pages at page {MAX_PAGES}; "
        f"stopping at {len(items)} rows.",
        file=sys.stderr,
    )
    return items


def fetch_touched_paths(
    repo: str, number: int, *, client: httpx.Client, headers: dict[str, str]
) -> list[str]:
    """File paths a PR changes, via the pulls/files endpoint."""
    rows = _paged(client, f"{API_ROOT}/repos/{repo}/pulls/{number}/files", headers)
    return [row["filename"] for row in rows if row.get("filename")]


def _is_maintainer_response(row: dict, pr_author: str) -> bool:
    user = row.get("user") or {}
    login = user.get("login") or ""
    if not login or login == pr_author:
        return False
    if user.get("type") == "Bot" or login.endswith("[bot]"):
        return False
    return row.get("author_association") in MAINTAINER_ASSOCIATIONS


def fetch_last_maintainer_activity(
    repo: str,
    number: int,
    pr_author: str,
    *,
    client: httpx.Client,
    headers: dict[str, str],
) -> datetime | None:
    """Latest maintainer comment/review timestamp on a PR, or None.

    Comments use `created_at` rather than `updated_at`, so editing an
    old comment does not count as a fresh response. Reviews use
    `submitted_at`; a PENDING review has none (and is invisible to
    everyone but its author anyway), so it is skipped.
    """
    latest: datetime | None = None
    sources = (
        (f"{API_ROOT}/repos/{repo}/issues/{number}/comments", "created_at"),
        (f"{API_ROOT}/repos/{repo}/pulls/{number}/reviews", "submitted_at"),
    )
    for url, ts_field in sources:
        for row in _paged(client, url, headers):
            if not _is_maintainer_response(row, pr_author):
                continue
            ts = _parse_ts(row.get(ts_field))
            if ts and (latest is None or ts > latest):
                latest = ts
    return latest


def enrich_prs(
    prs: list[PRRecord],
    *,
    http_client: httpx.Client | None = None,
    cache: dict | None = None,
    now: datetime | None = None,
) -> list[PRRecord]:
    """Return copies of `prs` with the enrichment fields filled in.

    `touched_paths` is fetched for every row; maintainer activity only
    for rows still open or draft. Passing one `cache` dict across a
    multi-kind run (`--kind all`) reuses results when the same PR
    surfaces under several kinds — the open snapshot overlaps almost
    every active/new row, so the cache roughly halves the request
    count. A failure on one PR degrades that row to its un-enriched
    form with a stderr warning instead of killing the weekly batch.
    """
    headers = request_headers()
    stamp = now or datetime.now(timezone.utc)
    cache = cache if cache is not None else {}
    owns_client = http_client is None
    client = http_client or httpx.Client(timeout=30.0)
    enriched: list[PRRecord] = []
    try:
        for pr in prs:
            key = (pr.repo, pr.pr_number)
            wants_activity = pr.status in ("open", "draft")
            try:
                entry = cache.get(key)
                if entry is None:
                    entry = {
                        "touched_paths": fetch_touched_paths(
                            pr.repo, pr.pr_number, client=client, headers=headers
                        )
                    }
                    cache[key] = entry
                if wants_activity and "activity" not in entry:
                    entry["activity"] = fetch_last_maintainer_activity(
                        pr.repo,
                        pr.pr_number,
                        pr.author,
                        client=client,
                        headers=headers,
                    )
            except httpx.HTTPError as exc:
                print(
                    f"WARNING: enrichment failed for {pr.repo}#{pr.pr_number}: {exc}",
                    file=sys.stderr,
                )
                enriched.append(pr)
                continue
            enriched.append(
                pr.model_copy(
                    update={
                        "touched_paths": list(entry["touched_paths"]),
                        "last_maintainer_activity_at": entry.get("activity"),
                        "enriched_at": stamp,
                    }
                )
            )
    finally:
        if owns_client:
            client.close()
    return enriched
