"""X (Twitter) indexer — fetch tweets from tracked handles.

Split out of the original `x_indexer.py` for clarity. Sub-modules:

- `_http`         X API client + tweet → `XPost` normaliser
- `loader`        `tracked_handles.yaml` flat / clusters parser
- `writer`        `x_posts` Firestore upserter
- `orchestrator`  per-week `resolve → fetch → write` composer
- `__main__`      CLI entrypoint (`python -m code.indexers.x_indexer`)

Importers should pin to the names re-exported here, not to the
sub-module paths.
"""

from code.indexers.x_indexer._http import (
    HandleNotFoundError,
    fetch_user_tweets,
    resolve_handle_to_id,
)
from code.indexers.x_indexer.loader import (
    load_handle_clusters,
    load_tracked_handles,
)
from code.indexers.x_indexer.orchestrator import run_for_week
from code.indexers.x_indexer.writer import X_COLLECTION, write_to_firestore

__all__ = [
    "HandleNotFoundError",
    "X_COLLECTION",
    "fetch_user_tweets",
    "load_handle_clusters",
    "load_tracked_handles",
    "resolve_handle_to_id",
    "run_for_week",
    "write_to_firestore",
]
