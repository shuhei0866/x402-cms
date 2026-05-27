"""Digest renderer — Firestore source data -> human HTML / agent JSON.

`read_week` is the single source-data accessor for both views. It pulls
the `source_data` collection, filters by ISO week, and rehydrates the
documents into `MergedPR` so callers always see a typed shape rather
than raw Firestore dicts. Both renderers consume the same list, so the
two views never drift in what counts as "this week's PRs".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import escape

import nh3
from google.cloud import firestore
from markdown_it import MarkdownIt

from code.schemas.commentary import Commentary
from code.schemas.pr import MergedPR
from code.schemas.x_post import XPost
from code.utils.firestore import build_client

COLLECTION = "source_data"
X_COLLECTION = "x_posts"
COMMENTARY_COLLECTION = "commentary"
DEFAULT_REPO = "x402-foundation/x402"


def read_week(
    week: str,
    project: str | None = None,
    *,
    client: firestore.Client | None = None,
) -> list[MergedPR]:
    """Load merged PRs for a given ISO week from Firestore.

    Results are sorted newest-first on `merged_at` so both views render
    in chronological reverse order without each renderer having to
    re-sort.
    """
    fs = build_client(client, project)
    docs = (
        fs.collection(COLLECTION)
        .where(filter=firestore.FieldFilter("week", "==", week))
        .stream()
    )
    prs = [MergedPR.model_validate(doc.to_dict()) for doc in docs]
    prs.sort(key=lambda p: p.merged_at, reverse=True)
    return prs


def read_x_posts_for_week(
    week: str,
    project: str | None = None,
    *,
    client: firestore.Client | None = None,
) -> list[XPost]:
    """Load X posts for a given ISO week from Firestore.

    Same shape as `read_week`: filter by `week`, rehydrate into the
    typed Pydantic model, sort newest-first on `created_at`. The
    renderer can then iterate without re-sorting.
    """
    fs = build_client(client, project)
    docs = (
        fs.collection(X_COLLECTION)
        .where(filter=firestore.FieldFilter("week", "==", week))
        .stream()
    )
    posts = [XPost.model_validate(doc.to_dict()) for doc in docs]
    posts.sort(key=lambda p: p.created_at, reverse=True)
    return posts


def read_commentary_for_week(
    week: str,
    project: str | None = None,
    *,
    client: firestore.Client | None = None,
) -> list[Commentary]:
    """Load commentary for a given ISO week from Firestore.

    Same shape as the other readers. The publish path only ever puts
    published commentary in the collection (unpublish/delete remove the
    doc), so everything read here is live. Sorted newest-first on
    `published_at`; a missing timestamp sorts last.
    """
    fs = build_client(client, project)
    docs = (
        fs.collection(COMMENTARY_COLLECTION)
        .where(filter=firestore.FieldFilter("week", "==", week))
        .stream()
    )
    commentaries = [Commentary.model_validate(doc.to_dict()) for doc in docs]
    # `published_at` is always stamped by the publish path, but guard a
    # missing one with a min-sentinel so the sort never compares None.
    _floor = datetime.min.replace(tzinfo=timezone.utc)
    commentaries.sort(
        key=lambda c: c.published_at or _floor,
        reverse=True,
    )
    return commentaries


def derive_recommendations(commentaries: list[Commentary]) -> list[Commentary]:
    """The ranked picks, derived (not a separate collection).

    Keeps only commentary with a `recommended_rank`, ordered 1→2→3.
    Rank uniqueness within a week is a publish-time invariant, so the
    sort is total here.
    """
    ranked = [c for c in commentaries if c.recommended_rank is not None]
    ranked.sort(key=lambda c: c.recommended_rank)  # type: ignore[arg-type,return-value]
    return ranked


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


@dataclass
class DigestBundle:
    """Single input to both renderers.

    Carries the typed source data for one ISO week (PRs, X posts) and
    the join layer (cross-references). The renderer no longer reaches
    into Firestore — it consumes this assembled shape.
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
    """Read both source collections for `week` and assemble a `DigestBundle`.

    Reuses `read_week` and `read_x_posts_for_week`, then runs
    `build_cross_references` on the two lists. `client` injection
    propagates to both readers so a single MagicMock can drive the
    whole assembly in tests. `handle_clusters` (handle → cluster name)
    is loaded once by the caller at server startup and threaded
    through every request — the renderer reads it to surface
    cluster-specific sections (currently the Japan spotlight).
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


# markdown-it with raw HTML disabled (the commonmark default), so a
# `<script>` in a body is escaped at conversion; nh3 is the second
# layer. Only the commentary body goes through this — the structural
# scaffold around it is our own trusted HTML and is not sanitised.
_MD = MarkdownIt()


def _md_to_safe_html(body_md: str) -> str:
    return nh3.clean(_MD.render(body_md))


def _single_target_index(
    commentaries: list[Commentary],
) -> dict[str, list[Commentary]]:
    """Commentaries with exactly one target, keyed by that ref."""
    index: dict[str, list[Commentary]] = {}
    for c in commentaries:
        if not c.week_level and len(c.target_refs) == 1:
            index.setdefault(c.target_refs[0], []).append(c)
    return index


JAPAN_CLUSTER = "japan"


def _posts_in_cluster(
    posts: list[XPost],
    handle_clusters: dict[str, str],
    cluster: str,
) -> list[XPost]:
    """X posts whose author handle maps to `cluster` in the curation."""
    return [p for p in posts if handle_clusters.get(p.author_handle) == cluster]


def render_html(bundle: DigestBundle) -> str:
    """Render the human-facing HTML view for a digest week.

    Order: week preface (prose, only if a week-level note exists) →
    Picks (ranked <ol>) → Merged PRs → X posts → Cross-references →
    end Commentary section (multi-target notes, anchored). Single-
    target notes are inlined as a <blockquote> on their PR / X item.
    Empty list sections keep their explicit "no … this week" line.
    PR/X user text stays HTML-escaped; commentary markdown is
    converted then nh3-sanitised.
    """
    single_idx = _single_target_index(bundle.commentaries)

    preface = "".join(
        f'<section class="preface">{_md_to_safe_html(c.body_md)}</section>'
        for c in bundle.commentaries
        if c.week_level
    )

    picks = derive_recommendations(bundle.commentaries)
    if picks:
        pick_items = "\n".join(
            f'<li><a href="#commentary-{escape(c.slug)}">{escape(c.title)}</a>'
            f' — {escape(c.tldr or "")}</li>'
            for c in picks
        )
        picks_html = f"<ol>\n{pick_items}\n</ol>"
    else:
        picks_html = "<p>No picks this week.</p>"

    pr_items = "\n".join(
        _html_pr_item(pr, single_idx) for pr in bundle.prs
    ) or "<li>No merged PRs this week.</li>"
    x_items = "\n".join(
        _html_x_item(p, single_idx) for p in bundle.x_posts
    ) or "<li>No X posts this week.</li>"

    jp_posts = _posts_in_cluster(
        bundle.x_posts, bundle.handle_clusters, JAPAN_CLUSTER
    )
    jp_items = "\n".join(
        _html_x_item(p, single_idx) for p in jp_posts
    ) or "<li>No Japan community posts this week.</li>"

    cross_items = "\n".join(
        _html_cross_item(cr) for cr in bundle.cross_references
    ) or "<li>No cross-references this week.</li>"

    multi = [
        c
        for c in bundle.commentaries
        if not c.week_level and len(c.target_refs) >= 2
    ]
    if multi:
        multi_html = "\n".join(
            f'<section id="commentary-{escape(c.slug)}">'
            f"<h3>{escape(c.title)}</h3>{_md_to_safe_html(c.body_md)}"
            f"</section>"
            for c in multi
        )
    else:
        multi_html = "<p>No additional commentary this week.</p>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>x402-cms — {escape(bundle.repo)} digest {escape(bundle.week)}</title>
</head>
<body>
<h1>{escape(bundle.repo)} — digest {escape(bundle.week)}</h1>
{preface}
<h2>Picks ({len(picks)})</h2>
{picks_html}

<h2>Merged PRs ({len(bundle.prs)})</h2>
<ul>
{pr_items}
</ul>

<h2>X posts ({len(bundle.x_posts)})</h2>
<ul>
{x_items}
</ul>

<h2>Japan community ({len(jp_posts)})</h2>
<ul>
{jp_items}
</ul>

<h2>Cross-references ({len(bundle.cross_references)})</h2>
<ul>
{cross_items}
</ul>

<h2>Commentary ({len(multi)})</h2>
{multi_html}
</body>
</html>
"""


def _blockquotes_for(
    ref: str, single_idx: dict[str, list[Commentary]]
) -> str:
    return "".join(
        f'<blockquote id="commentary-{escape(c.slug)}">'
        f"{_md_to_safe_html(c.body_md)}</blockquote>"
        for c in single_idx.get(ref, [])
    )


def _html_pr_item(pr: MergedPR, single_idx: dict[str, list[Commentary]]) -> str:
    bq = _blockquotes_for(f"pr:{pr.repo}#{pr.pr_number}", single_idx)
    return (
        f'<li><a href="{escape(pr.url)}">#{pr.pr_number}</a> '
        f'{escape(pr.title)} — <em>@{escape(pr.author)}</em>, '
        f"merged {pr.merged_at:%Y-%m-%d}{bq}</li>"
    )


def _html_x_item(post: XPost, single_idx: dict[str, list[Commentary]]) -> str:
    bq = _blockquotes_for(f"x:{post.post_id}", single_idx)
    return (
        f'<li><a href="{escape(post.url)}">@{escape(post.author_handle)}</a>: '
        f"{escape(post.text)}{bq}</li>"
    )


def _html_cross_item(cr: CrossReference) -> str:
    post_ids_html = ", ".join(escape(pid) for pid in cr.x_post_ids)
    return f"<li>{escape(cr.pr_ref)} — mentioned by X post id(s): {post_ids_html}</li>"


def render_agent_payload(bundle: DigestBundle) -> dict:
    """Render the agent-facing JSON payload for a digest week.

    `merged_prs` / `x_posts` / `commentary` are full rows; the agent
    paid for the interpretation so `commentary` ships the raw
    `body_md`. `cross_references` and `agent_recommendations` are
    normalised reference lists (ids / slugs) that the agent joins back
    to the full lists — the payload stays small even when the same
    note is both a pick and a body.
    """
    jp_posts = _posts_in_cluster(
        bundle.x_posts, bundle.handle_clusters, JAPAN_CLUSTER
    )
    return {
        "week": bundle.week,
        "repo": bundle.repo,
        "count": len(bundle.prs),
        "merged_prs": [pr.model_dump(mode="json") for pr in bundle.prs],
        "x_posts": [p.model_dump(mode="json") for p in bundle.x_posts],
        "cross_references": [
            {"pr_ref": cr.pr_ref, "x_post_ids": cr.x_post_ids}
            for cr in bundle.cross_references
        ],
        "commentary": [c.model_dump(mode="json") for c in bundle.commentaries],
        "agent_recommendations": [
            {
                "slug": c.slug,
                "recommended_rank": c.recommended_rank,
                "tldr": c.tldr,
            }
            for c in derive_recommendations(bundle.commentaries)
        ],
        "japan_section": [p.model_dump(mode="json") for p in jp_posts],
    }
