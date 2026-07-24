"""Candidate-surfacing helper for the curator.

`/x402-survey` runs this once a week so the human sees the field of
indexed data before writing commentary. Per the Phase 4 design,
the tool stays strictly RETRIEVAL + CLUSTERING — it does not write
commentary text, pick recommendations, or make any judgment call.
Observation and hypothesis are always written by the human, by hand,
first. This tool only helps the human not miss things.

Sections, action-oriented first:
  1. Snapshot               at-a-glance counts + cluster distribution
  2. PRs without commentary the actionable gap list
  3. Cross-references       PR ↔ tweet pairs already drawn (easy fodder)
  4. Stalled open PRs       maintainer-silent >8d — nudge or take over
  5. Cross-SDK parity gaps  single-SDK fixes with no counterpart — port
                            candidates
  6. Active PR authors      who shipped, with counts
  7. X cluster activity     per-handle post counts inside each cluster
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from google.cloud import firestore

from code.indexers.x_indexer import load_handle_clusters
from code.renderers.digest import (
    build_cross_references,
    read_commentary_for_week,
    read_week,
    read_x_posts_for_week,
)
from code.schemas.pr import MergedPR
from code.schemas.x_post import XPost
from code.survey.pr_field import (
    STALLED_AFTER_DAYS,
    ParityGap,
    StalledPR,
    find_parity_gaps,
    latest_pr_snapshots,
    read_all_pr_records,
    stalled_open_prs,
)
from code.utils.dates import previous_iso_week
from code.utils.firestore import build_client


def _pr_token(pr: MergedPR) -> str:
    return f"{pr.repo}#{pr.pr_number}"


def _covered_pr_tokens(commentaries) -> set[str]:
    covered: set[str] = set()
    for c in commentaries:
        for ref in c.target_refs:
            if ref.startswith("pr:"):
                covered.add(ref[3:])
    return covered


def _snapshot_section(
    prs: list[MergedPR],
    x_posts: list[XPost],
    commentaries: list,
    handle_clusters: dict[str, str],
) -> str:
    covered = _covered_pr_tokens(commentaries)
    cover_count = sum(1 for pr in prs if _pr_token(pr) in covered)

    lines = [
        "## Snapshot",
        "",
        f"{len(prs)} PRs · {len(x_posts)} tweets · "
        f"{len(commentaries)} commentary in vault "
        f"(covers {cover_count}/{len(prs)} PRs)",
    ]
    if handle_clusters and x_posts:
        cluster_counts = Counter(
            handle_clusters.get(p.author_handle, "unclustered") for p in x_posts
        )
        summary = ", ".join(
            f"{c} {n}"
            for c, n in sorted(cluster_counts.items())
            if c != "unclustered"
        )
        if summary:
            lines.extend(["", f"Cluster distribution: {summary}"])
    return "\n".join(lines)


def _prs_without_commentary_section(
    prs: list[MergedPR], commentaries: list
) -> str:
    covered = _covered_pr_tokens(commentaries)
    gap = [pr for pr in prs if _pr_token(pr) not in covered]
    lines = ["## PRs without commentary yet", ""]
    if not gap:
        lines.append("_All PRs this week have at least one commentary attached._")
        return "\n".join(lines)
    for pr in gap:
        lines.append(f"- #{pr.pr_number} {pr.title} — @{pr.author}")
    return "\n".join(lines)


def _cross_refs_section(cross_refs, x_posts: list[XPost]) -> str:
    by_id = {p.post_id: p for p in x_posts}
    lines = ["## Cross-references already drawn", ""]
    if not cross_refs:
        lines.append("_No cross-references this week._")
        return "\n".join(lines)
    for cr in cross_refs:
        handles = []
        for pid in cr.x_post_ids:
            post = by_id.get(pid)
            if post:
                handles.append(f"@{post.author_handle}")
        handles_str = ", ".join(handles) if handles else "—"
        lines.append(f"- {cr.pr_ref} ← {handles_str}")
    return "\n".join(lines)


def _stalled_prs_section(stalled: list[StalledPR], open_count: int, week: str) -> str:
    lines = [
        f"## Stalled open PRs (>{STALLED_AFTER_DAYS}d without maintainer response)",
        "",
    ]
    if open_count == 0:
        lines.append(
            f"_No open-PR snapshot rows for {week} — run the indexer with "
            "`--kind open` (or `all`) to populate this view._"
        )
        return "\n".join(lines)
    if not stalled:
        lines.append(
            f"_All {open_count} open PRs heard from a maintainer within "
            f"{STALLED_AFTER_DAYS} days._"
        )
        return "\n".join(lines)
    for s in stalled:
        if s.anchor == "maintainer_response":
            note = f"maintainer last responded {s.silent_days}d ago"
        elif s.anchor == "opened":
            note = f"no maintainer response since opening ({s.silent_days}d)"
        else:
            note = f"activity not indexed; last update {s.silent_days}d ago"
        lines.append(f"- #{s.pr.pr_number} {s.pr.title} — @{s.pr.author} · {note}")
    return "\n".join(lines)


def _parity_gap_section(gaps: list[ParityGap], corpus_size: int) -> str:
    lines = ["## Cross-SDK parity gaps", ""]
    if not gaps:
        lines.append(
            "_No single-SDK fixes missing counterparts across "
            f"{corpus_size} indexed PRs._"
        )
        return "\n".join(lines)
    for g in gaps:
        lines.append(
            f"- [{g.sdk}-only] #{g.pr.pr_number} {g.pr.title} — @{g.pr.author} "
            f"· no counterpart in {', '.join(g.missing)}"
        )
    lines.extend(
        [
            "",
            f"_Path + title-token match over {corpus_size} indexed PRs; "
            "verify by hand before porting._",
        ]
    )
    return "\n".join(lines)


def _active_pr_authors_section(prs: list[MergedPR]) -> str:
    lines = ["## Active PR authors", ""]
    if not prs:
        lines.append("_No PR activity this week._")
        return "\n".join(lines)
    counts = Counter(pr.author for pr in prs)
    for author, n in counts.most_common():
        lines.append(f"- @{author}: {n}")
    return "\n".join(lines)


def _x_cluster_activity_section(
    x_posts: list[XPost], handle_clusters: dict[str, str]
) -> str:
    lines = ["## X cluster activity", ""]
    if not x_posts:
        lines.append("_No X activity this week._")
        return "\n".join(lines)

    by_cluster: dict[str, Counter] = defaultdict(Counter)
    for p in x_posts:
        cluster = handle_clusters.get(p.author_handle, "unclustered")
        by_cluster[cluster][p.author_handle] += 1

    for cluster in sorted(by_cluster):
        # Hide "unclustered" only when curation is in place — when
        # there is no curation, every post is "unclustered" and we
        # still want to surface the activity.
        if cluster == "unclustered" and handle_clusters:
            continue
        lines.append(f"### {cluster}")
        for handle, n in by_cluster[cluster].most_common():
            lines.append(f"- @{handle}: {n}")
        lines.append("")
    return "\n".join(lines).rstrip()


def survey_week(
    week: str,
    *,
    project: str | None = None,
    client: firestore.Client | None = None,
    handle_clusters: dict[str, str] | None = None,
    now: datetime | None = None,
) -> str:
    """Return a Markdown candidate digest for `week`.

    Reads from Firestore (PRs, X posts, commentary) and groups by
    pre-existing dimensions (PR author, X handle, cluster, PR
    referenced by tweet, SDK directory). Does NOT call any LLM and does
    NOT decide what to write — the next step is the human, in the
    vault.

    The stalled and parity views read the whole PR corpus, not just
    `week`: staleness is measured on the week's open snapshot against
    `now` (injectable for tests; wall clock by default), and parity
    counterparts may live in any indexed week.
    """
    fs = build_client(client, project)
    handle_clusters = handle_clusters or {}
    now = now or datetime.now(timezone.utc)

    prs = read_week(week, client=fs)
    x_posts = read_x_posts_for_week(week, client=fs)
    commentaries = read_commentary_for_week(week, client=fs)
    cross_refs = build_cross_references(prs, x_posts)

    all_pr_records = read_all_pr_records(client=fs)
    week_records = [r for r in all_pr_records if r.week == week]
    open_count = sum(1 for r in week_records if r.status == "open")
    stalled = stalled_open_prs(week_records, now=now)
    snapshots = latest_pr_snapshots(all_pr_records)
    gaps = find_parity_gaps(snapshots)

    sections = [
        f"# x402 weekly survey — {week}",
        _snapshot_section(prs, x_posts, commentaries, handle_clusters),
        _prs_without_commentary_section(prs, commentaries),
        _cross_refs_section(cross_refs, x_posts),
        _stalled_prs_section(stalled, open_count, week),
        _parity_gap_section(gaps, len(snapshots)),
        _active_pr_authors_section(prs),
        _x_cluster_activity_section(x_posts, handle_clusters),
    ]
    return "\n\n".join(sections) + "\n"


DEFAULT_HANDLES_CONFIG = "config/tracked_handles.yaml"
FALLBACK_HANDLES_CONFIG = "config/tracked_handles.example.yaml"


def _resolve_handles_config(path: str | None) -> str | None:
    if path:
        return path
    if Path(DEFAULT_HANDLES_CONFIG).exists():
        return DEFAULT_HANDLES_CONFIG
    if Path(FALLBACK_HANDLES_CONFIG).exists():
        return FALLBACK_HANDLES_CONFIG
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Surface a week's indexed x402 data so the curator sees the "
            "field before writing commentary (retrieval + clustering, "
            "no judgment)."
        ),
    )
    parser.add_argument(
        "--week",
        default=None,
        help="ISO week label, e.g. '2026-W21'. Default: previous ISO week.",
    )
    parser.add_argument(
        "--handles-config",
        default=None,
        help=(
            "Path to the tracked handles yaml (for cluster info). "
            f"Default: {DEFAULT_HANDLES_CONFIG} if present, else "
            f"{FALLBACK_HANDLES_CONFIG}."
        ),
    )
    args = parser.parse_args()

    week = args.week or previous_iso_week()
    handles_path = _resolve_handles_config(args.handles_config)
    handle_clusters: dict[str, str] = {}
    if handles_path:
        handle_clusters = load_handle_clusters(handles_path)

    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    print(
        f"Surveying {week} (project: {project or 'ADC default'}, "
        f"handles: {handles_path or 'none'}).",
        file=sys.stderr,
    )

    md = survey_week(week, project=project, handle_clusters=handle_clusters)
    print(md, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
