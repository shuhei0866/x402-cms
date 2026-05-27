"""Human HTML view.

Order: week preface (prose, only if a week-level note exists) →
Picks (ranked <ol>) → Merged PRs → X posts → Japan community →
Cross-references → end Commentary section (multi-target notes,
anchored). Single-target notes are inlined as a <blockquote> on
their PR / X item.

Markdown is converted with markdown-it-py (raw HTML disabled, the
commonmark default) and then nh3-sanitised. The sanitiser only runs
on the body conversion — the structural scaffold (section /
blockquote / ol / anchors) is our own trusted HTML, which is why
the anchor ids survive. PR / X user text keeps the Phase-2
escaping.
"""

from __future__ import annotations

from html import escape

import nh3
from markdown_it import MarkdownIt

from code.renderers.digest.bundle import (
    JAPAN_CLUSTER,
    CrossReference,
    DigestBundle,
    derive_recommendations,
    posts_in_cluster,
)
from code.schemas.commentary import Commentary
from code.schemas.pr import MergedPR
from code.schemas.x_post import XPost

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


def render_html(bundle: DigestBundle) -> str:
    """Render the human-facing HTML view for a digest week."""
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

    jp_posts = posts_in_cluster(
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
