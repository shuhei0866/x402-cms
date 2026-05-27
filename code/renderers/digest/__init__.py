"""Digest renderer — Firestore source data → human HTML / agent JSON.

Split out of the original `digest.py` for clarity. Sub-modules:

- `readers`      three Firestore readers (PRs / X posts / commentary)
- `bundle`       `DigestBundle` + cross-references + recommendations +
                 the JP-cluster filter shared by both renderers
- `html`         the human HTML view
- `agent_json`   the agent JSON view

Importers should pin to the names re-exported here, not to the
sub-module paths.
"""

from code.renderers.digest.agent_json import render_agent_payload
from code.renderers.digest.bundle import (
    JAPAN_CLUSTER,
    CrossReference,
    DigestBundle,
    build_cross_references,
    derive_recommendations,
    load_digest_bundle,
    posts_in_cluster,
)
from code.renderers.digest.html import render_html
from code.renderers.digest.readers import (
    COLLECTION,
    COMMENTARY_COLLECTION,
    DEFAULT_REPO,
    X_COLLECTION,
    read_commentary_for_week,
    read_week,
    read_x_posts_for_week,
)

__all__ = [
    # collection constants
    "COLLECTION",
    "COMMENTARY_COLLECTION",
    "DEFAULT_REPO",
    "JAPAN_CLUSTER",
    "X_COLLECTION",
    # readers
    "read_commentary_for_week",
    "read_week",
    "read_x_posts_for_week",
    # bundle + join layer
    "CrossReference",
    "DigestBundle",
    "build_cross_references",
    "derive_recommendations",
    "load_digest_bundle",
    "posts_in_cluster",
    # renderers
    "render_agent_payload",
    "render_html",
]
