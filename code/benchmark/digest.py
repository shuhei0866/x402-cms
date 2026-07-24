"""Adapter between a frozen benchmark snapshot and the production renderers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from code.benchmark.capture import capture_edition
from code.benchmark.models import FrozenCapture
from code.indexers.x_indexer import load_handle_clusters
from code.renderers.digest import (
    CrossReference,
    DigestBundle,
    PublishedEdition,
    load_digest_bundle,
    read_published_editions,
    render_agent_payload,
    render_html,
)
from code.renderers.digest.topics import TopicRule, XKeywordRule, load_topics_config
from code.schemas.commentary import Commentary
from code.schemas.issue import IssueRecord
from code.schemas.pr import MergedPR, PRRecord
from code.schemas.x_post import XPost


def _dump_rows(rows: list[Any]) -> list[dict[str, Any]]:
    return [row.model_dump(mode="json") for row in rows]


def freeze_digest_snapshot(
    bundle: DigestBundle,
    *,
    published_editions: list[PublishedEdition],
    lang: str,
) -> dict[str, Any]:
    """Serialize every input consumed by either production renderer."""
    return {
        "schema_version": "r0-digest-snapshot-v1",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "week": bundle.week,
        "lang": lang,
        "bundle": {
            "repo": bundle.repo,
            "prs": _dump_rows(bundle.prs),
            "active_prs": _dump_rows(bundle.active_prs),
            "new_prs": _dump_rows(bundle.new_prs),
            "issues": _dump_rows(bundle.issues),
            "x_posts": _dump_rows(bundle.x_posts),
            "commentaries": _dump_rows(bundle.commentaries),
            "cross_references": [
                {"pr_ref": row.pr_ref, "x_post_ids": row.x_post_ids}
                for row in bundle.cross_references
            ],
            "handle_clusters": bundle.handle_clusters,
            "topic_rules": [
                {
                    "key": rule.key,
                    "label": rule.label,
                    "scopes": list(rule.scopes),
                    "keywords": list(rule.keywords),
                }
                for rule in bundle.topic_rules
            ],
            "x_keywords": [
                {
                    "key": rule.key,
                    "label": rule.label,
                    "patterns": list(rule.patterns),
                }
                for rule in bundle.x_keywords
            ],
        },
        "published_editions": [
            {
                "week": edition.week,
                "title": edition.title,
                "published_at": (
                    edition.published_at.isoformat() if edition.published_at else None
                ),
            }
            for edition in published_editions
        ],
        "coverage": {
            "merged_prs": len(bundle.prs),
            "active_prs": len(bundle.active_prs),
            "new_prs": len(bundle.new_prs),
            "issues": len(bundle.issues),
            "x_posts": len(bundle.x_posts),
            "commentaries": len(bundle.commentaries),
        },
    }


def thaw_digest_snapshot(
    snapshot: dict[str, Any],
) -> tuple[DigestBundle, list[PublishedEdition], str]:
    """Recreate the typed renderer boundary from its canonical snapshot."""
    if snapshot.get("schema_version") != "r0-digest-snapshot-v1":
        raise ValueError("unsupported digest snapshot schema")
    raw = snapshot["bundle"]
    bundle = DigestBundle(
        week=snapshot["week"],
        repo=raw["repo"],
        prs=[MergedPR.model_validate(row) for row in raw["prs"]],
        active_prs=[PRRecord.model_validate(row) for row in raw["active_prs"]],
        new_prs=[PRRecord.model_validate(row) for row in raw["new_prs"]],
        issues=[IssueRecord.model_validate(row) for row in raw["issues"]],
        x_posts=[XPost.model_validate(row) for row in raw["x_posts"]],
        commentaries=[Commentary.model_validate(row) for row in raw["commentaries"]],
        cross_references=[CrossReference(**row) for row in raw["cross_references"]],
        handle_clusters=dict(raw["handle_clusters"]),
        topic_rules=[
            TopicRule(
                key=row["key"],
                label=row["label"],
                scopes=tuple(row["scopes"]),
                keywords=tuple(row["keywords"]),
            )
            for row in raw["topic_rules"]
        ],
        x_keywords=[
            XKeywordRule(
                key=row["key"],
                label=row["label"],
                patterns=tuple(row["patterns"]),
            )
            for row in raw["x_keywords"]
        ],
    )
    editions = [
        PublishedEdition(
            week=row["week"],
            title=row["title"],
            published_at=(
                datetime.fromisoformat(row["published_at"])
                if row["published_at"]
                else None
            ),
        )
        for row in snapshot["published_editions"]
    ]
    return bundle, editions, str(snapshot["lang"])


def _render_snapshot_html(snapshot: object) -> str:
    bundle, editions, lang = thaw_digest_snapshot(snapshot)  # type: ignore[arg-type]
    return render_html(bundle, lang=lang, published_editions=editions)


def _render_snapshot_json(snapshot: object) -> dict[str, Any]:
    bundle, _, _ = thaw_digest_snapshot(snapshot)  # type: ignore[arg-type]
    return render_agent_payload(bundle)


def capture_live_digest(
    *,
    week: str,
    lang: str,
    handles_config: str | Path,
    topics_config: str | Path,
    artifact_dir: str | Path,
    project: str | None = None,
) -> FrozenCapture:
    """Read Firestore once and freeze both current production representations."""
    handle_clusters = load_handle_clusters(handles_config)
    topic_rules, x_keywords = load_topics_config(topics_config)

    def load_snapshot() -> dict[str, Any]:
        bundle = load_digest_bundle(
            week,
            project=project,
            handle_clusters=handle_clusters,
            topic_rules=topic_rules,
            x_keywords=x_keywords,
        )
        editions = read_published_editions(project=project)
        return freeze_digest_snapshot(
            bundle, published_editions=editions, lang=lang
        )

    return capture_edition(
        edition=week,
        source_loader=load_snapshot,
        render_html=_render_snapshot_html,
        render_json=_render_snapshot_json,
        artifact_dir=artifact_dir,
    )
