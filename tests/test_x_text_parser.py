"""Tests for `parse_pr_references` — the only X-post text parser.

The cross-reference primitive is `owner/repo#N`. The parser is meant
to be liberal about what surrounds a PR URL (trailing punctuation,
query strings, mid-sentence prefixes) but strict about what a PR URL
actually looks like, so issues / commit / blob / repo-root links do
not slip into the PR-reference set.

Output ordering is "order of first appearance" so renderer code can
display references in the same sequence they show up in the tweet.
"""

from __future__ import annotations

from code.indexers.x_text_parser import parse_pr_references


class TestParsePrReferences:
    def test_no_url_returns_empty(self) -> None:
        assert parse_pr_references("hello world, no links here") == []

    def test_single_pr_url(self) -> None:
        text = "shipped https://github.com/x402-foundation/x402/pull/2199"
        assert parse_pr_references(text) == ["x402-foundation/x402#2199"]

    def test_multiple_distinct_prs_preserve_order(self) -> None:
        text = (
            "two refs: "
            "https://github.com/x402-foundation/x402/pull/2199 and "
            "https://github.com/coinbase/agentkit/pull/77"
        )
        assert parse_pr_references(text) == [
            "x402-foundation/x402#2199",
            "coinbase/agentkit#77",
        ]

    def test_duplicate_pr_dedup_keeps_first(self) -> None:
        text = (
            "https://github.com/x402-foundation/x402/pull/2199 see also "
            "https://github.com/x402-foundation/x402/pull/2199"
        )
        assert parse_pr_references(text) == ["x402-foundation/x402#2199"]

    def test_trailing_punctuation_is_stripped(self) -> None:
        text = "PR https://github.com/x402-foundation/x402/pull/2199."
        assert parse_pr_references(text) == ["x402-foundation/x402#2199"]

    def test_query_string_and_fragment_are_tolerated(self) -> None:
        text = (
            "ref: https://github.com/x402-foundation/x402/pull/2199?w=1#issuecomment-99 "
            "is the thread"
        )
        assert parse_pr_references(text) == ["x402-foundation/x402#2199"]

    def test_issues_url_is_not_matched(self) -> None:
        text = "filed https://github.com/x402-foundation/x402/issues/100"
        assert parse_pr_references(text) == []

    def test_repo_root_url_is_not_matched(self) -> None:
        text = "see https://github.com/x402-foundation/x402"
        assert parse_pr_references(text) == []

    def test_commit_url_is_not_matched(self) -> None:
        text = (
            "see https://github.com/x402-foundation/x402/commit/abc123"
            " for the fix"
        )
        assert parse_pr_references(text) == []

    def test_http_scheme_also_matches(self) -> None:
        text = "http://github.com/owner/repo/pull/1"
        assert parse_pr_references(text) == ["owner/repo#1"]

    def test_case_in_owner_repo_is_preserved(self) -> None:
        # GitHub treats owner/repo names case-insensitively in the URL
        # but the canonical display preserves casing. We preserve what
        # the URL literally has.
        text = "https://github.com/Komlock-Lab/agent-cli/pull/42"
        assert parse_pr_references(text) == ["Komlock-Lab/agent-cli#42"]
