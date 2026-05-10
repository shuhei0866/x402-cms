"""Digest renderer — Firestore source data -> human HTML / agent JSON.

`read_week` is the single source-data accessor for both views. It pulls
the `source_data` collection, filters by ISO week, and rehydrates the
documents into `MergedPR` so callers always see a typed shape rather
than raw Firestore dicts. Both renderers consume the same list, so the
two views never drift in what counts as "this week's PRs".
"""

from __future__ import annotations

from html import escape

from google.cloud import firestore

from code.schemas.pr import MergedPR

COLLECTION = "source_data"
DEFAULT_REPO = "x402-foundation/x402"


def read_week(week: str, project: str | None = None) -> list[MergedPR]:
    """Load merged PRs for a given ISO week from Firestore.

    Results are sorted newest-first on `merged_at` so both views render
    in chronological reverse order without each renderer having to
    re-sort.
    """
    client = firestore.Client(project=project) if project else firestore.Client()
    docs = (
        client.collection(COLLECTION)
        .where(filter=firestore.FieldFilter("week", "==", week))
        .stream()
    )
    prs = [MergedPR.model_validate(doc.to_dict()) for doc in docs]
    prs.sort(key=lambda p: p.merged_at, reverse=True)
    return prs


def render_html(prs: list[MergedPR], week: str, repo: str = DEFAULT_REPO) -> str:
    """Render the human-facing HTML view for a digest week.

    Phase 1 keeps this deliberately minimal — a heading and an ordered
    list of PRs. Editorial commentary is layered on top in Phase 4 and
    the page styling is not yet a priority.
    """
    body_items = "\n".join(_html_item(pr) for pr in prs)
    if not body_items:
        body_items = "<li>No merged PRs in this week.</li>"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>x402-cms — {escape(repo)} digest {escape(week)}</title>
</head>
<body>
<h1>{escape(repo)} — merged PRs in {escape(week)}</h1>
<p>Total: {len(prs)} merged PR(s).</p>
<ul>
{body_items}
</ul>
</body>
</html>
"""


def _html_item(pr: MergedPR) -> str:
    return (
        f'<li><a href="{escape(pr.url)}">#{pr.pr_number}</a> '
        f'{escape(pr.title)} — <em>@{escape(pr.author)}</em>, '
        f'merged {pr.merged_at:%Y-%m-%d}</li>'
    )


def render_agent_payload(prs: list[MergedPR], week: str, repo: str = DEFAULT_REPO) -> dict:
    """Render the agent-facing JSON payload for a digest week."""
    return {
        "week": week,
        "repo": repo,
        "count": len(prs),
        "merged_prs": [pr.model_dump(mode="json") for pr in prs],
    }
