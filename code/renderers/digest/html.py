"""Human HTML view.

Order: adjacent-week links → week snapshot line → section nav (every
h2 carries a stable id, so the nav is the round-trip hub) → This week
at a glance (who moved / what's hot / where the talk is — the
first-view dashboard) → week preface (prose, only if a week-level
note exists) → Picks (ranked
<ol>) → Active discussions → Issues (both most-discussed first) →
Merged PRs → Newly opened (still-open rows visible, closed rows
folded) → X posts → Japan community (top-level posts visible, replies
folded per handle) → Cross-references → end Commentary section
(multi-target notes, anchored). Single-target notes are inlined as a
<blockquote> on their PR / X item.

The glance block is pure counting over the same mechanical signals;
its topic distribution comes from the curated scope/keyword mapping
in `config/topics.yaml` (see `topics.py`), so which signals count as
which topic is curation, not renderer judgment.

The ordering and folding rules are all mechanical (reply-or-not,
open-or-closed, comment counts, recency) — anything that *says* what
matters belongs to the commentary layer, not the renderer. Engagement
sorting (likes) is deliberately not used: it tracks follower count,
not signal.

Markdown is converted with markdown-it-py (raw HTML disabled, the
commonmark default) and then nh3-sanitised. The sanitiser only runs
on the body conversion — the structural scaffold (section /
blockquote / ol / anchors) is our own trusted HTML, which is why
the anchor ids survive. PR / X user text keeps the Phase-2
escaping.

Styling comes from the vendored classless Pico stylesheet linked in
the head (served at /static by the server). The markup itself stays
class-free semantic HTML, so this module carries no layout logic.
"""

from __future__ import annotations

from collections import Counter, defaultdict
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
from code.renderers.digest.topics import classify_title, count_x_keyword_hits
from code.utils.dates import shift_iso_week
from code.schemas.commentary import Commentary
from code.schemas.issue import IssueRecord
from code.schemas.pr import MergedPR, PRRecord
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


def _html_pr_record_item(
    pr: PRRecord, single_idx: dict[str, list[Commentary]]
) -> str:
    """An active / new PR row — status-aware, with inline commentary.

    The PR carries no `merged_at` (it is not merged), so the trailing
    phrase reports the state and the timestamp the kind keys on:
    `active` rows show the comment count and last-updated date, `new`
    rows show the opened date. Commentary attaches the same way it does
    to merged PRs — by the `pr:repo#N` token.
    """
    bq = _blockquotes_for(f"pr:{pr.repo}#{pr.pr_number}", single_idx)
    if pr.kind == "active":
        when = (
            f"updated {pr.updated_at:%Y-%m-%d}"
            if pr.updated_at
            else "recently active"
        )
        tail = f"{pr.status}, {pr.comments} comments, {when}"
    else:
        when = f"opened {pr.created_at:%Y-%m-%d}" if pr.created_at else "newly opened"
        tail = f"{pr.status}, {when}"
    return (
        f'<li><a href="{escape(pr.url)}">#{pr.pr_number}</a> '
        f'{escape(pr.title)} — <em>@{escape(pr.author)}</em>, '
        f"{tail}{bq}</li>"
    )


def _html_issue_item(issue: IssueRecord) -> str:
    when = (
        f"updated {issue.updated_at:%Y-%m-%d}" if issue.updated_at else issue.state
    )
    return (
        f'<li><a href="{escape(issue.url)}">#{issue.issue_number}</a> '
        f'{escape(issue.title)} — <em>@{escape(issue.author)}</em>, '
        f"{issue.state}, {issue.comments} comments, {when}</li>"
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


def _split_top_level(posts: list[XPost]) -> tuple[list[XPost], list[XPost]]:
    """Split posts into top-level entries and replies.

    Replies routinely dominate the raw feed (three quarters of a
    typical week), so this split is what keeps the section scannable.
    """
    top = [p for p in posts if p.in_reply_to_id is None]
    replies = [p for p in posts if p.in_reply_to_id is not None]
    return top, replies


def _posts_section_body(
    posts: list[XPost],
    single_idx: dict[str, list[Commentary]],
    empty_message: str,
) -> str:
    """Top-level posts as a visible list; replies folded per handle.

    Reply folds are ordered largest-first so the handles carrying the
    most conversation bulk are the easiest to audit. Everything stays
    on the page — folding hides, it never drops.
    """
    top, replies = _split_top_level(posts)
    if top:
        top_items = "\n".join(_html_x_item(p, single_idx) for p in top)
    elif replies:
        top_items = "<li>No top-level posts this week.</li>"
    else:
        top_items = f"<li>{empty_message}</li>"
    body = f"<ul>\n{top_items}\n</ul>"

    by_handle: dict[str, list[XPost]] = {}
    for post in replies:
        by_handle.setdefault(post.author_handle, []).append(post)
    for handle, handle_posts in sorted(
        by_handle.items(), key=lambda kv: len(kv[1]), reverse=True
    ):
        items = "\n".join(_html_x_item(p, single_idx) for p in handle_posts)
        body += (
            f"\n<details><summary>Replies from @{escape(handle)} "
            f"({len(handle_posts)})</summary>\n<ul>\n{items}\n</ul>\n</details>"
        )
    return body


def _new_prs_section_body(
    new_prs: list[PRRecord],
    single_idx: dict[str, list[Commentary]],
) -> str:
    """Still-open newcomers as a visible list; closed ones folded.

    A large share of newly opened PRs is closed within days (the
    ecosystem-listing wave), so only rows that can still be engaged
    with earn a visible slot.
    """
    open_rows = [p for p in new_prs if p.status in ("open", "draft")]
    closed_rows = [p for p in new_prs if p.status not in ("open", "draft")]
    if open_rows:
        open_items = "\n".join(
            _html_pr_record_item(p, single_idx) for p in open_rows
        )
    elif closed_rows:
        open_items = "<li>No still-open PRs this week.</li>"
    else:
        open_items = "<li>No newly opened PRs this week.</li>"
    body = f"<ul>\n{open_items}\n</ul>"
    if closed_rows:
        closed_items = "\n".join(
            _html_pr_record_item(p, single_idx) for p in closed_rows
        )
        body += (
            f"\n<details><summary>Closed without merge ({len(closed_rows)})"
            f"</summary>\n<ul>\n{closed_items}\n</ul>\n</details>"
        )
    return body


def _is_bot(author: str) -> bool:
    """GitHub's `[bot]` suffix, plus a name heuristic.

    The ecosystem-listing wave rides on accounts that are not
    registered GitHub Apps (`scotia1973-bot`, `clawdbotworker`), so a
    plain substring check is deliberate; a false positive only moves
    a row into the footnote, it drops nothing.
    """
    return author.endswith("[bot]") or "bot" in author.lower()


def _activity_phrase(counts: Counter[str]) -> str:
    parts = [
        f"{counts[k]} {k}" for k in ("merged", "active", "opened") if counts[k]
    ]
    if counts["issues"]:
        n = counts["issues"]
        parts.append(f"{n} issue" + ("s" if n != 1 else ""))
    return ", ".join(parts)


def _glance_html(bundle: DigestBundle) -> str:
    """The first-view dashboard: who moved / what's hot / where the talk is.

    Pure counting over signals the page already carries. The actor
    table folds bots into a footnote; What's hot ranks live threads
    (active PRs + issues) by comment count; the topic distribution is
    a lookup into the curated `topics.yaml` mapping with an explicit
    uncategorised bucket.
    """
    per_author: dict[str, Counter[str]] = defaultdict(Counter)
    for pr in bundle.prs:
        per_author[pr.author]["merged"] += 1
    for pr in bundle.active_prs:
        per_author[pr.author]["active"] += 1
    for pr in bundle.new_prs:
        per_author[pr.author]["opened"] += 1
    for issue in bundle.issues:
        per_author[issue.author]["issues"] += 1

    humans = [(a, c) for a, c in per_author.items() if not _is_bot(a)]
    bots = [(a, c) for a, c in per_author.items() if _is_bot(a)]
    humans.sort(key=lambda kv: sum(kv[1].values()), reverse=True)
    actor_rows = "\n".join(
        f"<tr><td>@{escape(a)}</td><td>{escape(_activity_phrase(c))}</td></tr>"
        for a, c in humans[:8]
    ) or '<tr><td colspan="2">No GitHub activity this week.</td></tr>'
    bot_items = sum(sum(c.values()) for _, c in bots)
    bot_note = (
        f"<p><small>{len(bots)} bot account(s), {bot_items} item(s), "
        f"kept out of the table.</small></p>"
        if bots
        else ""
    )

    top_posts, _ = _split_top_level(bundle.x_posts)
    x_counts = Counter(p.author_handle for p in top_posts)
    if x_counts:
        x_movers = " · ".join(
            f"@{escape(h)} {n}" for h, n in x_counts.most_common(8)
        )
        x_movers_html = f"<p>X top-level posts: {x_movers}</p>"
    else:
        x_movers_html = "<p>X top-level posts: none this week.</p>"

    hot: list[tuple[int, str]] = []
    for pr in bundle.active_prs:
        hot.append(
            (
                pr.comments,
                f'<li><a href="{escape(pr.url)}">#{pr.pr_number}</a> '
                f"{escape(pr.title)} — {pr.comments} comments (PR)</li>",
            )
        )
    for issue in bundle.issues:
        hot.append(
            (
                issue.comments,
                f'<li><a href="{escape(issue.url)}">#{issue.issue_number}</a> '
                f"{escape(issue.title)} — {issue.comments} comments (issue)</li>",
            )
        )
    hot.sort(key=lambda item: item[0], reverse=True)
    hot_html = (
        "<ol>\n" + "\n".join(li for _, li in hot[:5]) + "\n</ol>"
        if hot
        else "<p>No live discussions this week.</p>"
    )

    titles = [
        item.title
        for item in (
            *bundle.prs,
            *bundle.active_prs,
            *bundle.new_prs,
            *bundle.issues,
        )
    ]
    if bundle.topic_rules:
        topic_counts = Counter(
            classify_title(title, bundle.topic_rules) for title in titles
        )
        topic_rows = "\n".join(
            f"<tr><td>{escape(rule.label)}</td>"
            f"<td>{topic_counts.get(rule.key, 0)}</td></tr>"
            for rule in bundle.topic_rules
        )
        topic_rows += (
            f"\n<tr><td>uncategorised</td><td>{topic_counts.get(None, 0)}</td></tr>"
        )
        topics_html = (
            "<table>\n<thead><tr><th>GitHub topic</th><th>items</th></tr>"
            f"</thead>\n<tbody>\n{topic_rows}\n</tbody>\n</table>"
        )
    else:
        topics_html = (
            "<p>No topics config loaded — GitHub topic distribution "
            "unavailable.</p>"
        )

    cluster_counter: dict[str, Counter[str]] = defaultdict(Counter)
    for post in bundle.x_posts:
        cluster = bundle.handle_clusters.get(post.author_handle)
        if cluster is None:
            continue
        kind = "top" if post.in_reply_to_id is None else "reply"
        cluster_counter[cluster][kind] += 1
    if cluster_counter:
        cluster_rows = "\n".join(
            f"<tr><td>{escape(cluster)}</td><td>{c['top']}</td>"
            f"<td>{c['reply']}</td></tr>"
            for cluster, c in sorted(
                cluster_counter.items(),
                key=lambda kv: sum(kv[1].values()),
                reverse=True,
            )
        )
        clusters_html = (
            "\n<table>\n<thead><tr><th>X cluster</th><th>top-level</th>"
            f"<th>replies</th></tr></thead>\n<tbody>\n{cluster_rows}\n"
            "</tbody>\n</table>"
        )
    else:
        clusters_html = ""

    keyword_hits = count_x_keyword_hits(bundle.x_posts, bundle.x_keywords)
    if keyword_hits:
        keyword_line = " · ".join(
            f"{escape(rule.label)} {n}" for rule, n in keyword_hits
        )
        keywords_html = f"\n<p>X keyword hits: {keyword_line}</p>"
    else:
        keywords_html = ""

    return f"""<h2 id="glance">This week at a glance</h2>
<h3>Who moved</h3>
<table>
<thead><tr><th>GitHub</th><th>activity</th></tr></thead>
<tbody>
{actor_rows}
</tbody>
</table>
{bot_note}
{x_movers_html}
<h3>What's hot</h3>
{hot_html}
<h3>Where the talk is</h3>
{topics_html}{clusters_html}{keywords_html}"""


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
    active_items = "\n".join(
        _html_pr_record_item(pr, single_idx) for pr in bundle.active_prs
    ) or "<li>No active discussions this week.</li>"
    new_body = _new_prs_section_body(bundle.new_prs, single_idx)
    issue_items = "\n".join(
        _html_issue_item(i) for i in bundle.issues
    ) or "<li>No active issues this week.</li>"
    x_body = _posts_section_body(
        bundle.x_posts, single_idx, "No X posts this week."
    )

    jp_posts = posts_in_cluster(
        bundle.x_posts, bundle.handle_clusters, JAPAN_CLUSTER
    )
    jp_body = _posts_section_body(
        jp_posts, single_idx, "No Japan community posts this week."
    )

    top_posts, reply_posts = _split_top_level(bundle.x_posts)
    snapshot = (
        f"{len(bundle.prs)} merged · "
        f"{len(bundle.active_prs)} active discussions · "
        f"{len(bundle.new_prs)} newly opened · "
        f"{len(bundle.issues)} issues · "
        f"{len(top_posts)} X posts + {len(reply_posts)} replies"
    )
    glance = _glance_html(bundle)

    # Adjacent-week links; a malformed week label (the route accepts
    # any string) renders the page without them instead of failing.
    try:
        prev_week = shift_iso_week(bundle.week, -1)
        next_week = shift_iso_week(bundle.week, 1)
        week_nav = (
            f'<p><a href="/digest/{escape(prev_week)}">← {escape(prev_week)}</a>'
            f' · <a href="/digest/{escape(next_week)}">{escape(next_week)} →</a></p>'
        )
    except ValueError:
        week_nav = ""

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
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>x402-cms — {escape(bundle.repo)} digest {escape(bundle.week)}</title>
<link rel="stylesheet" href="/static/pico.classless.min.css">
</head>
<body>
<main>
<h1>{escape(bundle.repo)} — digest {escape(bundle.week)}</h1>
{week_nav}
<p>{snapshot}</p>
<nav aria-label="sections">
<ul>
<li><a href="#glance">Glance</a></li>
<li><a href="#picks">Picks</a></li>
<li><a href="#active">Active</a></li>
<li><a href="#issues">Issues</a></li>
<li><a href="#merged">Merged</a></li>
<li><a href="#new">New</a></li>
<li><a href="#x-posts">X posts</a></li>
<li><a href="#japan">Japan</a></li>
<li><a href="#cross-references">Cross-refs</a></li>
<li><a href="#commentary">Commentary</a></li>
</ul>
</nav>
{glance}
{preface}
<h2 id="picks">Picks ({len(picks)})</h2>
{picks_html}

<h2 id="active">Active discussions ({len(bundle.active_prs)})</h2>
<ul>
{active_items}
</ul>

<h2 id="issues">Issues ({len(bundle.issues)})</h2>
<ul>
{issue_items}
</ul>

<h2 id="merged">Merged PRs ({len(bundle.prs)})</h2>
<ul>
{pr_items}
</ul>

<h2 id="new">Newly opened ({len(bundle.new_prs)})</h2>
{new_body}

<h2 id="x-posts">X posts ({len(bundle.x_posts)})</h2>
{x_body}

<h2 id="japan">Japan community ({len(jp_posts)})</h2>
{jp_body}

<h2 id="cross-references">Cross-references ({len(bundle.cross_references)})</h2>
<ul>
{cross_items}
</ul>

<h2 id="commentary">Commentary ({len(multi)})</h2>
{multi_html}
</main>
</body>
</html>
"""
