"""Human HTML view.

The page is glance-first. Everything above the fold is the focus:
adjacent-week links → week snapshot strip → section nav → This week
at a glance (who moved / what's hot / where the talk is — the
first-view dashboard) → week preface (prose, only if a week-level
note exists) → Picks (ranked <ol>). Below that, every body section is
a collapsed <details> the reader opens on demand — Active discussions,
Issues (both most-discussed first), Merged PRs, Newly opened, X posts,
Japan community, Cross-references, Commentary. This keeps the reader's
attention narrowed to one screen instead of a long uniform scroll; the
glance already surfaces the week's hot threads and movers, so the full
lists are drill-down, not front matter. A tiny progressive-enhancement
script opens a section when its anchor is navigated to; with no JS the
sections simply start closed and open on click. Each id is stable, so
the nav and deep links still resolve.

Within a section the earlier rules hold: newly-opened shows still-open
rows with closed ones folded, X posts show top-level with replies
folded per handle, and single-target notes inline as a <blockquote> on
their PR / X item.

The presentation is a design layer over classless Pico (see
`static/digest.css`). One grammar runs through the page: a unit of
activity is weighted by its heat (comment count), rendered as a
right-aligned tabular number over a magnitude bar. That weight is the
same mechanical signal the readers already sort by — the design just
lets it drive visual weight, not only position. Nothing that *says*
what matters enters here; that stays in the commentary layer. Merged
and newly-opened rows carry no comment heat (they are settled / brand
new), so they show a small state tag instead of a bar. Engagement
metrics (likes) are deliberately never a weight.

The glance block is pure counting over the same signals; its topic
distribution comes from the curated scope/keyword mapping in
`config/topics.yaml` (see `topics.py`), so which signals count as
which topic is curation, not renderer judgment.

Markdown is converted with markdown-it-py (raw HTML disabled, the
commonmark default) and then nh3-sanitised. The sanitiser only runs
on the body conversion — the structural scaffold is our own trusted
HTML, which is why the class hooks and anchor ids survive. PR / X user
text keeps the Phase-2 escaping.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
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
from code.schemas.commentary import Commentary
from code.schemas.issue import IssueRecord
from code.schemas.pr import MergedPR, PRRecord
from code.schemas.x_post import XPost
from code.utils.dates import shift_iso_week

_MD = MarkdownIt()


def _md_to_safe_html(body_md: str) -> str:
    return nh3.clean(_MD.render(body_md))


def _fmt_date(dt: datetime) -> str:
    """`Jul 4` — month abbrev + day, avoiding platform `%-d` quirks."""
    return f"{dt:%b} {dt.day}"


def _pct(value: int, ceiling: int) -> int:
    """Bar width as an integer percent of the section's top value."""
    return round(value / ceiling * 100) if ceiling > 0 else 0


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


# --- shared row grammar --------------------------------------------------


def _heat_mark(count: int, ceiling: int) -> str:
    """A right-aligned tabular count over an amber magnitude bar."""
    return (
        '<span class="mark">'
        f'<span class="n">{count}</span>'
        f'<span class="bar amber"><i style="--w:{_pct(count, ceiling)}%"></i>'
        "</span></span>"
    )


def _tag_mark(label: str) -> str:
    """A small state tag for rows that carry no comment heat."""
    return f'<span class="mark tag"><span class="label">{escape(label)}</span></span>'


def _meta(*parts: str) -> str:
    """Join already-escaped metadata fragments with a middot."""
    return " · ".join(p for p in parts if p)


def _row(mark: str, url: str, id_label: str, title: str, meta: str, bq: str = "",
         cls: str = "") -> str:
    """One activity row: mark cell + (id · title · meta) + inline note."""
    row_cls = f"row {cls}".strip()
    return (
        f'<li class="{row_cls}">{mark}'
        '<span class="row-main">'
        f'<a class="row-id" href="{escape(url)}">{escape(id_label)}</a>'
        f'<span class="row-title">{escape(title)}</span>'
        f'<span class="row-meta">{meta}</span>'
        f"{bq}</span></li>"
    )


def _merged_row(pr: MergedPR, single_idx: dict[str, list[Commentary]]) -> str:
    bq = _blockquotes_for(f"pr:{pr.repo}#{pr.pr_number}", single_idx)
    meta = _meta(f"@{escape(pr.author)}", f"merged {escape(_fmt_date(pr.merged_at))}")
    return _row(
        _tag_mark("merged"), pr.url, f"#{pr.pr_number}", pr.title, meta, bq, "settled"
    )


def _active_row(
    pr: PRRecord, ceiling: int, single_idx: dict[str, list[Commentary]]
) -> str:
    bq = _blockquotes_for(f"pr:{pr.repo}#{pr.pr_number}", single_idx)
    when = f"updated {escape(_fmt_date(pr.updated_at))}" if pr.updated_at else "active"
    meta = _meta(f"@{escape(pr.author)}", escape(pr.status), when)
    return _row(
        _heat_mark(pr.comments, ceiling), pr.url, f"#{pr.pr_number}", pr.title, meta, bq
    )


def _new_row(pr: PRRecord, single_idx: dict[str, list[Commentary]]) -> str:
    bq = _blockquotes_for(f"pr:{pr.repo}#{pr.pr_number}", single_idx)
    when = f"opened {escape(_fmt_date(pr.created_at))}" if pr.created_at else "new"
    meta = _meta(f"@{escape(pr.author)}", escape(pr.status), when)
    return _row(
        _tag_mark("new"), pr.url, f"#{pr.pr_number}", pr.title, meta, bq, "settled"
    )


def _issue_row(issue: IssueRecord, ceiling: int) -> str:
    when = f"updated {escape(_fmt_date(issue.updated_at))}" if issue.updated_at else ""
    meta = _meta(f"@{escape(issue.author)}", escape(issue.state), when)
    return _row(
        _heat_mark(issue.comments, ceiling),
        issue.url,
        f"#{issue.issue_number}",
        issue.title,
        meta,
    )


def _x_row(post: XPost, single_idx: dict[str, list[Commentary]]) -> str:
    bq = _blockquotes_for(f"x:{post.post_id}", single_idx)
    return (
        f'<li class="xrow"><a class="row-id" href="{escape(post.url)}">'
        f"@{escape(post.author_handle)}</a>"
        f'<span class="xtext">{escape(post.text)}</span>{bq}</li>'
    )


def _html_cross_item(cr: CrossReference) -> str:
    post_ids_html = ", ".join(escape(pid) for pid in cr.x_post_ids)
    return f"<li>{escape(cr.pr_ref)} — mentioned by X post id(s): {post_ids_html}</li>"


# --- section bodies ------------------------------------------------------


def _split_top_level(posts: list[XPost]) -> tuple[list[XPost], list[XPost]]:
    """Split posts into top-level entries and replies.

    Replies routinely dominate the raw feed (three quarters of a
    typical week), so this split is what keeps the section scannable.
    """
    top = [p for p in posts if p.in_reply_to_id is None]
    replies = [p for p in posts if p.in_reply_to_id is not None]
    return top, replies


def _active_section_body(
    active_prs: list[PRRecord], single_idx: dict[str, list[Commentary]]
) -> str:
    if not active_prs:
        return '<ul class="rows"><li class="empty">No active discussions this week.</li></ul>'
    ceiling = max(p.comments for p in active_prs)
    rows = "\n".join(_active_row(p, ceiling, single_idx) for p in active_prs)
    return f'<ul class="rows">\n{rows}\n</ul>'


def _issues_section_body(issues: list[IssueRecord]) -> str:
    if not issues:
        return '<ul class="rows"><li class="empty">No active issues this week.</li></ul>'
    ceiling = max(i.comments for i in issues)
    rows = "\n".join(_issue_row(i, ceiling) for i in issues)
    return f'<ul class="rows">\n{rows}\n</ul>'


def _merged_section_body(
    prs: list[MergedPR], single_idx: dict[str, list[Commentary]]
) -> str:
    if not prs:
        return '<ul class="rows"><li class="empty">No merged PRs this week.</li></ul>'
    rows = "\n".join(_merged_row(p, single_idx) for p in prs)
    return f'<ul class="rows">\n{rows}\n</ul>'


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
        top_items = "\n".join(_x_row(p, single_idx) for p in top)
    elif replies:
        top_items = '<li class="empty">No top-level posts this week.</li>'
    else:
        top_items = f'<li class="empty">{empty_message}</li>'
    body = f'<ul class="xposts">\n{top_items}\n</ul>'

    by_handle: dict[str, list[XPost]] = {}
    for post in replies:
        by_handle.setdefault(post.author_handle, []).append(post)
    for handle, handle_posts in sorted(
        by_handle.items(), key=lambda kv: len(kv[1]), reverse=True
    ):
        items = "\n".join(_x_row(p, single_idx) for p in handle_posts)
        body += (
            f"\n<details><summary>Replies from @{escape(handle)} "
            f'({len(handle_posts)})</summary>\n<ul class="xposts">\n{items}\n'
            "</ul>\n</details>"
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
        open_items = "\n".join(_new_row(p, single_idx) for p in open_rows)
    elif closed_rows:
        open_items = '<li class="empty">No still-open PRs this week.</li>'
    else:
        open_items = '<li class="empty">No newly opened PRs this week.</li>'
    body = f'<ul class="rows">\n{open_items}\n</ul>'
    if closed_rows:
        closed_items = "\n".join(_new_row(p, single_idx) for p in closed_rows)
        body += (
            f"\n<details><summary>Closed without merge ({len(closed_rows)})"
            f'</summary>\n<ul class="rows">\n{closed_items}\n</ul>\n</details>'
        )
    return body


# --- glance dashboard ----------------------------------------------------


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


def _dist_rows(pairs: list[tuple[str, int]]) -> str:
    """Volume bars: label · blue magnitude bar · count, largest-scaled."""
    ceiling = max((n for _, n in pairs), default=0)
    return "\n".join(
        f'<div class="dist"><span class="dlabel">{escape(label)}</span>'
        f'<span class="bar blue"><i style="--w:{_pct(n, ceiling)}%"></i></span>'
        f'<span class="dnum">{n}</span></div>'
        for label, n in pairs
    )


def _glance_movers(bundle: DigestBundle) -> str:
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

    if humans:
        mover_rows = "\n".join(
            f'<li><span class="who">@{escape(a)}</span>'
            f'<span class="what">{escape(_activity_phrase(c))}</span></li>'
            for a, c in humans[:8]
        )
    else:
        mover_rows = '<li class="empty">No GitHub activity this week.</li>'
    movers = f'<ul class="movers">\n{mover_rows}\n</ul>'

    if bots:
        bot_items = sum(sum(c.values()) for _, c in bots)
        movers += (
            f'<p class="foot">{len(bots)} bot account(s) · '
            f"{bot_items} item(s) · folded</p>"
        )

    top_posts, _ = _split_top_level(bundle.x_posts)
    x_counts = Counter(p.author_handle for p in top_posts)
    if x_counts:
        x_movers = " · ".join(
            f"@{escape(h)} {n}" for h, n in x_counts.most_common(6)
        )
        movers += f'<p class="foot"><span class="mono">X: {x_movers}</span></p>'
    return f"<div class=\"panel\"><h3>Who moved</h3>\n{movers}</div>"


def _glance_hot(bundle: DigestBundle) -> str:
    hot: list[tuple[int, str, str, int]] = []  # (comments, url, title, number)
    for pr in bundle.active_prs:
        hot.append((pr.comments, pr.url, pr.title, pr.pr_number))
    for issue in bundle.issues:
        hot.append((issue.comments, issue.url, issue.title, issue.issue_number))
    hot.sort(key=lambda t: t[0], reverse=True)

    if not hot:
        body = '<ul class="rows compact"><li class="empty">No live discussions this week.</li></ul>'
    else:
        ceiling = hot[0][0]
        rows = "\n".join(
            _row(
                _heat_mark(comments, ceiling),
                url,
                f"#{number}",
                title,
                "",
            )
            for comments, url, title, number in hot[:5]
        )
        body = f'<ul class="rows compact">\n{rows}\n</ul>'
    return f'<div class="panel"><h3>What\'s hot</h3>\n{body}</div>'


def _glance_talk(bundle: DigestBundle) -> str:
    groups = ""

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
        pairs = [
            (rule.label, topic_counts.get(rule.key, 0)) for rule in bundle.topic_rules
        ]
        pairs.append(("uncategorised", topic_counts.get(None, 0)))
        groups += (
            f'<div class="distgroup"><h4>GitHub topics</h4>\n{_dist_rows(pairs)}</div>'
        )
    else:
        groups += (
            '<div class="distgroup"><p class="foot">No topics config loaded — '
            "GitHub topic distribution unavailable.</p></div>"
        )

    cluster_counter: dict[str, Counter[str]] = defaultdict(Counter)
    for post in bundle.x_posts:
        cluster = bundle.handle_clusters.get(post.author_handle)
        if cluster is None:
            continue
        kind = "top" if post.in_reply_to_id is None else "reply"
        cluster_counter[cluster][kind] += 1
    if cluster_counter:
        pairs = [
            (f"{cluster} (+{c['reply']})" if c["reply"] else cluster, c["top"])
            for cluster, c in sorted(
                cluster_counter.items(),
                key=lambda kv: sum(kv[1].values()),
                reverse=True,
            )
        ]
        groups += (
            f'<div class="distgroup"><h4>X clusters — top-level (+replies)</h4>\n'
            f"{_dist_rows(pairs)}</div>"
        )

    keyword_hits = count_x_keyword_hits(bundle.x_posts, bundle.x_keywords)
    if keyword_hits:
        keyword_line = " · ".join(
            f"{escape(rule.label)} {n}" for rule, n in keyword_hits
        )
        groups += f'<p class="foot"><span class="mono">X keywords: {keyword_line}</span></p>'

    return f'<div class="panel"><h3>Where the talk is</h3>\n{groups}</div>'


def _glance_html(bundle: DigestBundle) -> str:
    """The first-view dashboard: who moved / what's hot / where the talk is.

    Pure counting over signals the page already carries, laid out as
    three panels sharing the page's heat / volume bar grammar.
    """
    return (
        '<h2 id="glance">This week at a glance</h2>\n'
        '<div class="glance">\n'
        f"{_glance_movers(bundle)}\n"
        f"{_glance_hot(bundle)}\n"
        f"{_glance_talk(bundle)}\n"
        "</div>"
    )


# --- page ----------------------------------------------------------------


def _section(sid: str, name: str, count: int, body: str) -> str:
    """A body section collapsed by default — the drill-down grammar.

    The summary reads as the old section header (name + muted count);
    the content is present in the DOM but folded, so the page stays
    short until the reader opens it. `sid` is the stable anchor the
    nav and the hash-open script target.
    """
    return (
        f'<details class="section" id="{sid}">'
        f'<summary><span class="sname">{escape(name)}</span> '
        f'<span class="count">{count}</span></summary>\n{body}\n</details>'
    )


# Progressive enhancement: open a collapsed section when it is the
# navigation target (nav click, deep link, hashchange). With no JS the
# sections still work — they start closed and open on click.
_HASH_OPEN_JS = """<script>
(function () {
  function openTarget() {
    var el = location.hash && document.getElementById(location.hash.slice(1));
    if (el && el.tagName === "DETAILS") el.open = true;
  }
  addEventListener("hashchange", openTarget);
  openTarget();
})();
</script>"""


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

    active_body = _active_section_body(bundle.active_prs, single_idx)
    issues_body = _issues_section_body(bundle.issues)
    merged_body = _merged_section_body(bundle.prs, single_idx)
    new_body = _new_prs_section_body(bundle.new_prs, single_idx)
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
        '<div class="snapshot">'
        f"<span><b>{len(bundle.prs)}</b> merged</span>"
        f"<span><b>{len(bundle.active_prs)}</b> active</span>"
        f"<span><b>{len(bundle.new_prs)}</b> newly opened</span>"
        f"<span><b>{len(bundle.issues)}</b> issues</span>"
        f"<span><b>{len(top_posts)}</b> X posts "
        f"<em>+ {len(reply_posts)} replies</em></span>"
        "</div>"
    )
    glance = _glance_html(bundle)

    # Adjacent-week links; a malformed week label (the route accepts
    # any string) renders the page without them instead of failing.
    try:
        prev_week = shift_iso_week(bundle.week, -1)
        next_week = shift_iso_week(bundle.week, 1)
        week_nav = (
            f'<p class="weeknav"><a href="/digest/{escape(prev_week)}">'
            f"← {escape(prev_week)}</a> · "
            f'<a href="/digest/{escape(next_week)}">{escape(next_week)} →</a></p>'
        )
    except ValueError:
        week_nav = ""

    cross_items = "\n".join(
        _html_cross_item(cr) for cr in bundle.cross_references
    ) or '<li class="empty">No cross-references this week.</li>'
    cross_body = f'<ul class="rows">\n{cross_items}\n</ul>'

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
        multi_html = '<p class="empty">No additional commentary this week.</p>'

    sections = "\n".join(
        (
            _section("active", "Active discussions", len(bundle.active_prs), active_body),
            _section("issues", "Issues", len(bundle.issues), issues_body),
            _section("merged", "Merged PRs", len(bundle.prs), merged_body),
            _section("new", "Newly opened", len(bundle.new_prs), new_body),
            _section("x-posts", "X posts", len(bundle.x_posts), x_body),
            _section("japan", "Japan community", len(jp_posts), jp_body),
            _section(
                "cross-references",
                "Cross-references",
                len(bundle.cross_references),
                cross_body,
            ),
            _section("commentary", "Commentary", len(multi), multi_html),
        )
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>x402-cms — {escape(bundle.repo)} digest {escape(bundle.week)}</title>
<link rel="stylesheet" href="/static/pico.classless.min.css">
<link rel="stylesheet" href="/static/digest.css">
</head>
<body>
<main>
<h1>{escape(bundle.repo)} — digest {escape(bundle.week)}</h1>
{week_nav}
{snapshot}
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
<h2 id="picks">Picks <span class="count">{len(picks)}</span></h2>
{picks_html}
{sections}
</main>
{_HASH_OPEN_JS}
</body>
</html>
"""
