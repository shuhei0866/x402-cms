"""tracked_handles.yaml loader — flat list or `clusters:` mapping.

`load_tracked_handles` returns the flattened handle list the
indexer's fetch loop wants. `load_handle_clusters` returns the
handle → cluster mapping the renderer uses to surface per-cluster
sections (currently the Japan spotlight). Both functions accept the
same two YAML shapes so the OSS example template and the curated
production file stay parseable by the same code.
"""

from __future__ import annotations

from pathlib import Path

import yaml


def _normalise_handle_entry(entry: object) -> str | None:
    if entry is None:
        return None
    cleaned = str(entry).strip().lstrip("@").strip()
    return cleaned or None


def _read_handles_yaml(path: str | Path) -> object:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_tracked_handles(path: str | Path) -> list[str]:
    """Read tracked X handles as a flat list (cluster info discarded).

    Two YAML shapes are accepted:

    1. **Flat list** — the original OSS-template form:

           - phdargen
           - CarsonRoscoe

    2. **Structured clusters** — the curated production form:

           clusters:
             protocol_core: [x402_org, base]
             japan: [0x_natto, winor30]

    The indexer's fetch loop does not care which cluster a handle
    belongs to, only the renderer does. Blank entries are skipped and
    leading `@` is stripped.
    """
    raw = _read_handles_yaml(path)
    if raw is None:
        return []
    handles: list[str] = []
    if isinstance(raw, list):
        candidates: list[object] = raw
    elif isinstance(raw, dict) and isinstance(raw.get("clusters"), dict):
        candidates = []
        for entries in raw["clusters"].values():
            if isinstance(entries, list):
                candidates.extend(entries)
    else:
        raise ValueError(
            f"{path}: expected a flat list or a 'clusters:' mapping"
        )
    for entry in candidates:
        cleaned = _normalise_handle_entry(entry)
        if cleaned:
            handles.append(cleaned)
    return handles


def load_handle_clusters(path: str | Path) -> dict[str, str]:
    """Read the handle → cluster-name mapping, or `{}` for flat yaml.

    The renderer reads this to surface per-cluster sections (e.g. the
    Japan community spotlight). A flat OSS-template yaml has no
    cluster information; the renderer treats an empty map as "skip
    cluster-grouped sections".
    """
    raw = _read_handles_yaml(path)
    if not isinstance(raw, dict):
        return {}
    clusters = raw.get("clusters")
    if not isinstance(clusters, dict):
        return {}
    mapping: dict[str, str] = {}
    for cluster_name, entries in clusters.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            cleaned = _normalise_handle_entry(entry)
            if cleaned:
                mapping[cleaned] = str(cluster_name)
    return mapping
