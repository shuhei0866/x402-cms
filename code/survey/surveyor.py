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
  3. Stalled open PRs       open PRs the project has not answered
  4. Cross-SDK parity gaps  a fix in one SDK, missing from the others
  5. Cross-references       PR ↔ tweet pairs already drawn (easy fodder)
  6. Active PR authors      who shipped, with counts
  7. X cluster activity     per-handle post counts inside each cluster

Sections 3 and 4 serve a second reader of the same data: not the
curator deciding what to write about, but the contributor deciding
where to put their hands. Both are still pure retrieval — one sorts by
elapsed silence, the other by a path-and-title match — and neither
suggests what to do about what it finds.
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
    read_all_prs_for_week,
    read_commentary_for_week,
    read_week,
    read_x_posts_for_week,
)
from code.schemas.pr import MergedPR, PRRecord
from code.schemas.x_post import XPost
from code.survey.parity import ParityGap, find_parity_gaps
from code.survey.stalled import (
    OPEN_STATUSES,
    STALLED_AFTER_DAYS,
    StalledPR,
    find_stalled_prs,
    undatable_open_prs,
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
    stalled: list[StalledPR],
    gaps: list[ParityGap],
) -> str:
    covered = _covered_pr_tokens(commentaries)
    cover_count = sum(1 for pr in prs if _pr_token(pr) in covered)

    lines = [
        "## Snapshot",
        "",
        f"{len(prs)} PRs · {len(x_posts)} tweets · "
        f"{len(commentaries)} commentary in vault "
        f"(covers {cover_count}/{len(prs)} PRs)",
        "",
        f"Scouting: {len(stalled)} stalled open PR(s) · "
        f"{len(gaps)} cross-SDK parity gap(s)",
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


def _stalled_section(
    stalled: list[StalledPR],
    all_prs: list[PRRecord],
    threshold_days: int,
) -> str:
    lines = [
        "## Stalled open PRs",
        "",
        f"_Open PRs with no maintainer reaction for more than "
        f"{threshold_days} days. Measured against the indexed snapshot, "
        f"so a survey of an old week reports that week's silence, not "
        f"today's. Two uses: deciding whether one of your own PRs has "
        f"gone quiet enough to be worth a nudge, and finding someone "
        f"else's PR to pick up._",
        "",
    ]
    undatable = undatable_open_prs(all_prs)
    if undatable:
        lines.extend(
            [
                f"_{len(undatable)} open PR(s) carry neither a maintainer "
                f"reaction nor a creation time and are excluded — re-run "
                f"the indexer to date them._",
                "",
            ]
        )
    if not stalled:
        open_count = sum(1 for pr in all_prs if pr.status in OPEN_STATUSES)
        lines.append(
            f"_None of the {open_count} open PR(s) this week have been "
            f"silent that long._"
        )
        return "\n".join(lines)

    for s in stalled:
        pr = s.pr
        if s.anchor == "maintainer":
            who = ", ".join(f"@{r}" for r in pr.maintainer_responders) or "a maintainer"
            last = f"last reaction {s.since.date().isoformat()} by {who}"
        else:
            last = f"no maintainer reaction since it opened {s.since.date().isoformat()}"
        lines.append(
            f"- #{pr.pr_number} {pr.title} — @{pr.author} · "
            f"silent {s.silent_days}d · {last} · {pr.url}"
        )
    return "\n".join(lines)


def _parity_gaps_section(gaps: list[ParityGap], all_prs: list[PRRecord]) -> str:
    lines = [
        "## Cross-SDK parity gaps",
        "",
        "_Fixes that touched one SDK directory only, with nothing in "
        "the other SDKs that matches them by changed paths and title. "
        "Candidates for porting sideways, which is auditing work rather "
        "than authoring work. The counterpart search covers this week's "
        "indexed PRs alone, so a port that landed in a different week "
        "still shows up here as a gap._",
        "",
    ]
    unindexed = [pr for pr in all_prs if not pr.changed_paths]
    if unindexed:
        lines.extend(
            [
                f"_{len(unindexed)} of {len(all_prs)} PR(s) have no indexed "
                f"file paths and were skipped — run the indexer without "
                f"`--no-enrich` to cover them._",
                "",
            ]
        )
    if not gaps:
        lines.append("_No single-SDK fix is missing a counterpart this week._")
        return "\n".join(lines)

    for gap in gaps:
        pr = gap.pr
        missing = ", ".join(gap.missing_sdks)
        row = (
            f"- [{gap.sdk}] #{pr.pr_number} {pr.title} — @{pr.author} "
            f"({pr.status}) · missing in {missing}"
        )
        if gap.matched_sdks:
            row += f" · already matched in {', '.join(gap.matched_sdks)}"
        if pr.paths_truncated:
            row += " · path list truncated, may touch more SDKs"
        lines.append(f"{row} · {pr.url}")
        if gap.sample_paths:
            lines.append(f"  - touched: {', '.join(gap.sample_paths)}")
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
    stalled_after_days: int = STALLED_AFTER_DAYS,
) -> str:
    """Return a Markdown candidate digest for `week`.

    Reads from Firestore (PRs, X posts, commentary) and groups by
    pre-existing dimensions (PR author, X handle, cluster, PR
    referenced by tweet, SDK directory, elapsed maintainer silence).
    Does NOT call any LLM and does NOT decide what to write — the next
    step is the human, in the vault.

    Read-only against Firestore and against nothing else: the two
    scouting sections work off fields the indexer already stored, so a
    survey never reaches out to GitHub and never needs a token.
    """
    fs = build_client(client, project)
    handle_clusters = handle_clusters or {}
    now = now or datetime.now(timezone.utc)

    prs = read_week(week, client=fs)
    all_prs = read_all_prs_for_week(week, client=fs)
    x_posts = read_x_posts_for_week(week, client=fs)
    commentaries = read_commentary_for_week(week, client=fs)
    cross_refs = build_cross_references(prs, x_posts)
    stalled = find_stalled_prs(all_prs, now=now, threshold_days=stalled_after_days)
    gaps = find_parity_gaps(all_prs)

    sections = [
        f"# x402 weekly survey — {week}",
        _snapshot_section(prs, x_posts, commentaries, handle_clusters, stalled, gaps),
        _prs_without_commentary_section(prs, commentaries),
        _stalled_section(stalled, all_prs, stalled_after_days),
        _parity_gaps_section(gaps, all_prs),
        _cross_refs_section(cross_refs, x_posts),
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
    parser.add_argument(
        "--stalled-after-days",
        type=int,
        default=STALLED_AFTER_DAYS,
        help=(
            "Days of maintainer silence before an open PR is listed as "
            f"stalled (default: {STALLED_AFTER_DAYS}, the longest first "
            "response observed on this repo)."
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

    md = survey_week(
        week,
        project=project,
        handle_clusters=handle_clusters,
        stalled_after_days=args.stalled_after_days,
    )
    print(md, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
