"""Digest renderer — Firestore source data → human HTML / agent JSON.

Split out of the original `digest.py` for clarity. Sub-modules:

- `readers`      Firestore readers (merged / active / new PRs, X posts,
                 commentary, issues)
- `bundle`       `DigestBundle` + cross-references + recommendations +
                 the JP-cluster filter shared by both renderers
- `html`         the human HTML view
- `agent_json`   the agent JSON view

Importers should pin to the names re-exported here, not to the
sub-module paths.
"""

from code.renderers.digest.agent_json import render_agent_payload
from code.renderers.digest.archive import render_archive, render_home, render_not_found
from code.renderers.digest.bundle import (
    JAPAN_CLUSTER,
    CrossReference,
    DigestBundle,
    build_cross_references,
    digest_has_content,
    derive_recommendations,
    load_digest_bundle,
    posts_in_cluster,
)
from code.renderers.digest.html import render_html
from code.renderers.digest.publication import PublishedEdition, read_published_editions
from code.renderers.digest.readers import (
    COLLECTION,
    COMMENTARY_COLLECTION,
    DEFAULT_REPO,
    ISSUES_COLLECTION,
    X_COLLECTION,
    read_all_prs_for_week,
    read_commentary_for_week,
    read_issues_for_week,
    read_prs_by_kind,
    read_week,
    read_x_posts_for_week,
)

__all__ = [
    # collection constants
    "COLLECTION",
    "COMMENTARY_COLLECTION",
    "DEFAULT_REPO",
    "ISSUES_COLLECTION",
    "JAPAN_CLUSTER",
    "X_COLLECTION",
    # readers
    "read_all_prs_for_week",
    "read_commentary_for_week",
    "read_issues_for_week",
    "read_prs_by_kind",
    "read_week",
    "read_x_posts_for_week",
    "read_published_editions",
    # bundle + join layer
    "CrossReference",
    "DigestBundle",
    "PublishedEdition",
    "build_cross_references",
    "digest_has_content",
    "derive_recommendations",
    "load_digest_bundle",
    "posts_in_cluster",
    # renderers
    "render_agent_payload",
    "render_archive",
    "render_html",
    "render_home",
    "render_not_found",
]
