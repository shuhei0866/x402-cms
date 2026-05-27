"""Assembly layer: source rows + joins → a single `DigestBundle`.

The bundle is the renderer's input boundary. Both `render_html` and
`render_agent_payload` consume it, so the join primitives
(`CrossReference`, `derive_recommendations`, JP cluster filter) live
here next to the dataclass.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from google.cloud import firestore

from code.renderers.digest.readers import (
    read_commentary_for_week,
    read_week,
    read_x_posts_for_week,
)
from code.schemas.commentary import Commentary
from code.schemas.pr import MergedPR
from code.schemas.x_post import XPost
from code.utils.firestore import build_client

DEFAULT_REPO = "x402-foundation/x402"
JAPAN_CLUSTER = "japan"


def _pr_ref(pr: MergedPR) -> str:
    """The canonical `owner/repo#N` token a tweet's `referenced_prs` carries."""
    return f"{pr.repo}#{pr.pr_number}"


@dataclass
class CrossReference:
    """One PR's bucket of X-post ids that mention it.

    The renderer iterates these in PR-list order; the agent JSON
    serialises them as `{pr_ref, x_post_ids}` so consumers join back
    to the `x_posts` list by id (normalised, not denormalised, so the
    payload stays small even when several PRs share a tweet).
    """

    pr_ref: str
    x_post_ids: list[str] = field(default_factory=list)


def build_cross_references(
    prs: list[MergedPR],
    x_posts: list[XPost],
) -> list[CrossReference]:
    """Join X posts to PRs by their `referenced_prs` tokens.

    Only references that resolve to a PR present in `prs` are
    surfaced — a tweet citing last-week's PR is dropped from the
    cross-reference layer (the renderer can still find the raw
    reference inside the x_post's `referenced_prs`). Output order
    follows `prs`; within a key, post order follows `x_posts`.
    """
    pr_refs_in_scope = {_pr_ref(pr) for pr in prs}

    grouped: dict[str, list[str]] = {}
    for post in x_posts:
        for ref in post.referenced_prs:
            if ref not in pr_refs_in_scope:
                continue
            grouped.setdefault(ref, []).append(post.post_id)

    result: list[CrossReference] = []
    for pr in prs:
        key = _pr_ref(pr)
        if key in grouped:
            result.append(CrossReference(pr_ref=key, x_post_ids=grouped[key]))
    return result


def derive_recommendations(commentaries: list[Commentary]) -> list[Commentary]:
    """The ranked picks, derived (not a separate collection).

    Keeps only commentary with a `recommended_rank`, ordered 1→2→3.
    Rank uniqueness within a week is a publish-time invariant, so the
    sort is total here.
    """
    ranked = [c for c in commentaries if c.recommended_rank is not None]
    ranked.sort(key=lambda c: c.recommended_rank)  # type: ignore[arg-type,return-value]
    return ranked


def posts_in_cluster(
    posts: list[XPost],
    handle_clusters: dict[str, str],
    cluster: str,
) -> list[XPost]:
    """X posts whose author handle maps to `cluster` in the curation."""
    return [p for p in posts if handle_clusters.get(p.author_handle) == cluster]


@dataclass
class DigestBundle:
    """Single input to both renderers.

    Carries the typed source data for one ISO week (PRs, X posts,
    commentary) and the join layer (cross-references). The renderer
    no longer reaches into Firestore — it consumes this assembled
    shape. `handle_clusters` is the curated handle → cluster map the
    Service loads once at startup and threads through every request.
    """

    week: str
    repo: str
    prs: list[MergedPR]
    x_posts: list[XPost]
    cross_references: list[CrossReference]
    commentaries: list[Commentary] = field(default_factory=list)
    handle_clusters: dict[str, str] = field(default_factory=dict)


def load_digest_bundle(
    week: str,
    *,
    repo: str = DEFAULT_REPO,
    project: str | None = None,
    client: firestore.Client | None = None,
    handle_clusters: dict[str, str] | None = None,
) -> DigestBundle:
    """Read all three source collections for `week` and assemble a bundle.

    Reuses the readers, runs `build_cross_references`, and returns a
    fully assembled `DigestBundle`. `client` injection propagates to
    every reader so a single MagicMock can drive the whole assembly
    in tests.
    """
    fs = build_client(client, project)
    prs = read_week(week, client=fs)
    x_posts = read_x_posts_for_week(week, client=fs)
    commentaries = read_commentary_for_week(week, client=fs)
    cross_references = build_cross_references(prs, x_posts)
    return DigestBundle(
        week=week,
        repo=repo,
        prs=prs,
        x_posts=x_posts,
        cross_references=cross_references,
        commentaries=commentaries,
        handle_clusters=handle_clusters or {},
    )
