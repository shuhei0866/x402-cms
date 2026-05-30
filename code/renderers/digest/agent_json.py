"""Agent JSON view.

Full-row lists (`merged_prs`, `active_prs`, `new_prs`, `issues`,
`x_posts`, `commentary`, `japan_section`) ride alongside normalised
reference lists (`cross_references`,
`agent_recommendations`) so the payload stays small even when the
same note is both a pick and a body. The top-level key set is
pinned by `test_renderer_payload.test_top_level_keys_present` — an
accidental add/rename trips it.
"""

from __future__ import annotations

from code.renderers.digest.bundle import (
    JAPAN_CLUSTER,
    DigestBundle,
    derive_recommendations,
    posts_in_cluster,
)


def render_agent_payload(bundle: DigestBundle) -> dict:
    """Render the agent-facing JSON payload for a digest week."""
    jp_posts = posts_in_cluster(
        bundle.x_posts, bundle.handle_clusters, JAPAN_CLUSTER
    )
    return {
        "week": bundle.week,
        "repo": bundle.repo,
        "count": len(bundle.prs),
        "merged_prs": [pr.model_dump(mode="json") for pr in bundle.prs],
        "active_prs": [pr.model_dump(mode="json") for pr in bundle.active_prs],
        "new_prs": [pr.model_dump(mode="json") for pr in bundle.new_prs],
        "issues": [i.model_dump(mode="json") for i in bundle.issues],
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
