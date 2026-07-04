"""Topic classification for the at-a-glance view.

Maps mechanical signals — conventional-commit scope tokens and title
keywords — onto curated categories loaded from `config/topics.yaml`
(private; `.example.yaml` ships in the repo). The mapping table is
the editorial act; this module only looks things up, it never judges.

Match rules, in order:

1. The title's conventional-commit tokens (the type, plus the scope
   split on `/`) are checked against each category's `scopes`, in
   category order — author-declared scope is the strongest signal.
2. If no scope matches, the whole title is searched for each
   category's `keywords` (word-boundary, case-insensitive), again in
   category order.
3. No match → `None`; the renderer buckets it as uncategorised and
   shows the bucket, so a thin mapping table reads as "uncategorised
   is large", never as a silently wrong distribution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from code.schemas.x_post import XPost

_CONVENTIONAL_RE = re.compile(r"^(\w+)\s*(?:\(([^)]+)\))?\s*:")


@dataclass(frozen=True)
class TopicRule:
    """One category row from the curated topics config."""

    key: str
    label: str
    scopes: tuple[str, ...]
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class XKeywordRule:
    """One X-post keyword bucket from the curated topics config."""

    key: str
    label: str
    patterns: tuple[str, ...]


def load_topics_config(path: str | Path) -> tuple[list[TopicRule], list[XKeywordRule]]:
    """Load (categories, x_keywords) from the curated yaml.

    Both lists keep file order — order is the tiebreak when several
    categories could claim a title, so it is part of the curation.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    rules = [
        TopicRule(
            key=str(c["key"]),
            label=str(c.get("label", c["key"])),
            scopes=tuple(str(s).lower() for s in c.get("scopes", [])),
            keywords=tuple(str(k).lower() for k in c.get("keywords", [])),
        )
        for c in raw.get("categories", [])
    ]
    x_keywords = [
        XKeywordRule(
            key=str(k["key"]),
            label=str(k.get("label", k["key"])),
            patterns=tuple(str(p).lower() for p in k.get("patterns", [])),
        )
        for k in raw.get("x_keywords", [])
    ]
    return rules, x_keywords


def _conventional_tokens(title: str) -> list[str]:
    """Type + scope tokens of a conventional-commit title, lowercased.

    `spec(xrpl): …` → ["spec", "xrpl"]; `feat(go/svm): …` →
    ["feat", "go", "svm"]; a bare title yields no tokens.
    """
    m = _CONVENTIONAL_RE.match(title)
    if not m:
        return []
    tokens = [m.group(1).lower()]
    if m.group(2):
        tokens.extend(t.strip().lower() for t in m.group(2).split("/") if t.strip())
    return tokens


def _keyword_hit(text_lower: str, keyword: str) -> bool:
    return re.search(rf"\b{re.escape(keyword)}\b", text_lower) is not None


def classify_title(title: str, rules: list[TopicRule]) -> str | None:
    """Return the key of the first matching category, or None."""
    tokens = set(_conventional_tokens(title))
    if tokens:
        for rule in rules:
            if tokens.intersection(rule.scopes):
                return rule.key
    title_lower = title.lower()
    for rule in rules:
        if any(_keyword_hit(title_lower, kw) for kw in rule.keywords):
            return rule.key
    return None


def count_x_keyword_hits(
    posts: list[XPost], x_keywords: list[XKeywordRule]
) -> list[tuple[XKeywordRule, int]]:
    """Count posts matching each keyword bucket (a post may hit several)."""
    counts: list[tuple[XKeywordRule, int]] = []
    lowered = [p.text.lower() for p in posts]
    for rule in x_keywords:
        n = sum(
            1
            for text in lowered
            if any(_keyword_hit(text, pat) for pat in rule.patterns)
        )
        counts.append((rule, n))
    return counts
