"""Tests for the topic classifier behind the at-a-glance view.

The classifier is a lookup, not a judge: scope tokens first (author-
declared, strongest), title keywords second, file order breaks ties,
no match stays None so the uncategorised bucket is honest.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from code.renderers.digest.topics import (
    TopicRule,
    XKeywordRule,
    classify_title,
    count_x_keyword_hits,
    load_topics_config,
)
from code.schemas.x_post import XPost

SPECS = TopicRule(
    key="specs",
    label="specs & schemes",
    scopes=("spec", "specs"),
    keywords=("scheme", "conformance"),
)
SDK = TopicRule(
    key="sdk",
    label="SDK & chains",
    scopes=("python", "go", "svm", "typescript"),
    keywords=("reference implementation", "near", "sui"),
)
RULES = [SPECS, SDK]


class TestClassifyTitle:
    def test_scope_token_matches(self) -> None:
        assert classify_title("spec(xrpl): add exact scheme", RULES) == "specs"

    def test_compound_scope_splits_on_slash(self) -> None:
        assert classify_title("feat(go/svm): recent blockhash", RULES) == "sdk"

    def test_scope_beats_keyword_across_rule_order(self) -> None:
        # Title carries a `specs` keyword ("scheme") but the declared
        # scope says python — the author's own scoping wins.
        title = "fix(python): align scheme parsing"
        assert classify_title(title, RULES) == "sdk"

    def test_bare_title_falls_back_to_keywords(self) -> None:
        assert classify_title("NEAR reference implementation", RULES) == "sdk"

    def test_keyword_needs_word_boundary(self) -> None:
        # "sui" must not fire inside "suitable".
        assert classify_title("a suitable title", RULES) is None

    def test_first_rule_wins_on_keyword_tie(self) -> None:
        # "conformance" (specs) and "near" (sdk) both present — file
        # order decides, which makes the order itself curation.
        title = "conformance vectors for near"
        assert classify_title(title, RULES) == "specs"

    def test_no_match_returns_none(self) -> None:
        assert classify_title("fix labelers", RULES) is None


class TestLoadTopicsConfig:
    def test_loads_categories_and_x_keywords_in_file_order(
        self, tmp_path: Path
    ) -> None:
        cfg = tmp_path / "topics.yaml"
        cfg.write_text(
            """
categories:
  - key: specs
    label: specs & schemes
    scopes: [spec]
    keywords: [scheme]
  - key: sdk
    scopes: [python]
    keywords: []
x_keywords:
  - key: agentic
    label: agentic payments
    patterns: [agentic, ap2]
""",
            encoding="utf-8",
        )
        rules, x_keywords = load_topics_config(cfg)
        assert [r.key for r in rules] == ["specs", "sdk"]
        assert rules[0].label == "specs & schemes"
        # label falls back to the key when omitted.
        assert rules[1].label == "sdk"
        assert x_keywords[0].patterns == ("agentic", "ap2")

    def test_empty_file_yields_empty_rules(self, tmp_path: Path) -> None:
        cfg = tmp_path / "topics.yaml"
        cfg.write_text("", encoding="utf-8")
        assert load_topics_config(cfg) == ([], [])


def _post(post_id: str, text: str) -> XPost:
    return XPost(
        post_id=post_id,
        author_handle="someone",
        author_id="1",
        created_at=datetime(2026, 5, 5, tzinfo=timezone.utc),
        text=text,
        url=f"https://x.com/someone/status/{post_id}",
        week="2026-W19",
    )


class TestCountXKeywordHits:
    def test_counts_posts_per_bucket_case_insensitive(self) -> None:
        agentic = XKeywordRule(
            key="agentic", label="agentic payments", patterns=("agentic", "ap2")
        )
        posts = [
            _post("1", "Agentic payments are coming"),
            _post("2", "AP2 interop draft"),
            _post("3", "unrelated"),
        ]
        assert count_x_keyword_hits(posts, [agentic]) == [(agentic, 2)]

    def test_zero_hit_buckets_stay_visible(self) -> None:
        mcp = XKeywordRule(key="mcp", label="MCP", patterns=("mcp",))
        assert count_x_keyword_hits([_post("1", "nothing here")], [mcp]) == [
            (mcp, 0)
        ]
