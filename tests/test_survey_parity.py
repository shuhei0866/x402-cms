"""Tests for the cross-SDK parity matcher.

The matcher rests on two mechanical claims — a path tells you which
SDK a change lives in, and a stripped title tells you what the change
is about — so the tests pin those claims separately from the gap
detection built on top of them. The false-positive direction matters
more than the false-negative one: a missed gap costs an opportunity,
whereas a wrong one sends the curator to read a diff that was never
portable, so the matcher is exercised on both.
"""

from __future__ import annotations

from code.schemas.pr import PRRecord
from code.survey.parity import (
    find_parity_gaps,
    is_fix,
    sdks_touched,
    title_tokens,
    titles_match,
)


def _pr(
    number: int,
    title: str,
    *,
    paths: list[str] | None = None,
    labels: list[str] | None = None,
    status: str = "merged",
    truncated: bool = False,
) -> PRRecord:
    return PRRecord(
        repo="x402-foundation/x402",
        pr_number=number,
        title=title,
        author="phdargen",
        url=f"https://github.com/x402-foundation/x402/pull/{number}",
        week="2026-W21",
        status=status,
        kind="merged" if status == "merged" else "active",
        labels=labels or [],
        changed_paths=paths or [],
        paths_truncated=truncated,
    )


class TestSdksTouched:
    def test_top_level_sdk_directory(self) -> None:
        assert sdks_touched(["python/x402/exact.py"]) == {"python"}

    def test_nested_example_directory_resolves_by_segment(self) -> None:
        # Segment matching, not prefix matching, so the monorepo can
        # grow layouts without this table growing with it.
        assert sdks_touched(
            ["examples/typescript/servers/express/index.ts"]
        ) == {"typescript"}

    def test_js_folds_into_the_typescript_family(self) -> None:
        assert sdks_touched(["examples/javascript/client/index.js"]) == {"typescript"}

    def test_spec_and_docs_paths_belong_to_no_sdk(self) -> None:
        assert sdks_touched(["specs/x402-specification.md", "README.md"]) == set()

    def test_a_file_named_after_an_sdk_is_not_an_sdk_change(self) -> None:
        # `docs/python.md` is writing about the SDK, not touching it.
        assert sdks_touched(["docs/python.md"]) == set()

    def test_multiple_paths_union_into_multiple_sdks(self) -> None:
        assert sdks_touched(
            ["go/pkg/x402/verify.go", "python/x402/verify.py"]
        ) == {"go", "python"}

    def test_prefixed_directory_still_resolves(self) -> None:
        assert sdks_touched(["packages/x402-go/client.go"]) == {"go"}


class TestTitleTokens:
    def test_drops_conventional_type_but_keeps_the_scope(self) -> None:
        # `fix:` says only that it is a fix; `(facilitator)` says what
        # the fix is about, so the scope survives into the token set.
        assert title_tokens("fix(facilitator): settle timeout") == {
            "facilitator",
            "settle",
            "timeout",
        }

    def test_drops_sdk_names_so_a_port_matches_its_original(self) -> None:
        assert title_tokens("fix(python): retry on 402") == title_tokens(
            "fix(typescript): retry on 402"
        )

    def test_drops_single_character_noise(self) -> None:
        assert "x" not in title_tokens("fix: x in the settle path")


class TestTitlesMatch:
    def test_differently_worded_report_of_the_same_symptom_matches(self) -> None:
        left = title_tokens("fix: settle response header not set on 402 retry")
        right = title_tokens("fix(python): settle header missing on retry")
        assert titles_match(left, right)

    def test_two_unrelated_fixes_do_not_match(self) -> None:
        left = title_tokens("fix: typo in README")
        right = title_tokens("fix: retry backoff on facilitator timeout")
        assert not titles_match(left, right)

    def test_one_shared_word_is_a_coincidence_not_a_port(self) -> None:
        left = title_tokens("fix: settle timeout on mainnet")
        right = title_tokens("fix: settle")
        assert not titles_match(left, right)

    def test_empty_token_sets_never_match(self) -> None:
        assert not titles_match(set(), set())


class TestIsFix:
    def test_conventional_fix_prefix(self) -> None:
        assert is_fix(_pr(1, "fix(python): retry"))

    def test_plain_english_title(self) -> None:
        assert is_fix(_pr(1, "Fixed the broken settle path"))

    def test_bug_label_without_a_fix_word_in_the_title(self) -> None:
        assert is_fix(_pr(1, "settle path returns 500", labels=["bug"]))

    def test_a_feature_is_not_a_fix(self) -> None:
        assert not is_fix(_pr(1, "feat: add batch settlement scheme"))

    def test_fix_inside_another_word_does_not_count(self) -> None:
        assert not is_fix(_pr(1, "feat: add prefix handling to the router"))


class TestFindParityGaps:
    def test_single_sdk_fix_with_no_counterpart_is_a_gap(self) -> None:
        gaps = find_parity_gaps(
            [_pr(1, "fix: settle header missing on retry", paths=["python/x402/settle.py"])]
        )
        assert len(gaps) == 1
        assert gaps[0].sdk == "python"
        assert gaps[0].missing_sdks == ["typescript", "go"]
        assert gaps[0].sample_paths == ["python/x402/settle.py"]

    def test_a_fix_ported_to_every_other_sdk_is_not_a_gap(self) -> None:
        gaps = find_parity_gaps(
            [
                _pr(1, "fix: settle header missing on retry", paths=["python/x402/s.py"]),
                _pr(2, "fix: settle header missing on retry", paths=["typescript/src/s.ts"]),
                _pr(3, "fix: settle header missing on retry", paths=["go/pkg/s.go"]),
            ]
        )
        assert gaps == []

    def test_a_partly_ported_fix_is_still_a_gap_for_what_is_left(self) -> None:
        gaps = find_parity_gaps(
            [
                _pr(1, "fix: settle header missing on retry", paths=["python/x402/s.py"]),
                _pr(2, "fix: settle header missing on retry", paths=["typescript/src/s.ts"]),
            ]
        )
        # Both sides now name go as the one that never got it.
        assert {g.pr.pr_number for g in gaps} == {1, 2}
        assert all(g.missing_sdks == ["go"] for g in gaps)
        assert gaps[0].matched_sdks and gaps[0].matched_sdks != [gaps[0].sdk]

    def test_the_counterpart_may_be_titled_as_a_feature(self) -> None:
        # Whoever carried the fix across may not have called it a fix;
        # only the subject PR has to look like one.
        gaps = find_parity_gaps(
            [
                _pr(1, "fix: settle header missing on retry", paths=["python/x402/s.py"]),
                _pr(2, "feat: settle header missing on retry", paths=["typescript/src/s.ts"]),
                _pr(3, "chore: settle header missing on retry", paths=["go/pkg/s.go"]),
            ]
        )
        assert gaps == []

    def test_a_pr_spanning_two_sdks_carries_its_own_port(self) -> None:
        gaps = find_parity_gaps(
            [
                _pr(
                    1,
                    "fix: settle header missing",
                    paths=["python/x402/s.py", "typescript/src/s.ts", "go/pkg/s.go"],
                )
            ]
        )
        assert gaps == []

    def test_a_feature_confined_to_one_sdk_is_not_reported(self) -> None:
        gaps = find_parity_gaps(
            [_pr(1, "feat: add mainnet config", paths=["python/x402/config.py"])]
        )
        assert gaps == []

    def test_a_change_outside_every_sdk_directory_is_not_reported(self) -> None:
        gaps = find_parity_gaps(
            [_pr(1, "fix: typo in the spec", paths=["specs/x402-specification.md"])]
        )
        assert gaps == []

    def test_prs_without_indexed_paths_sit_out(self) -> None:
        # Absent data is not evidence of a gap.
        assert find_parity_gaps([_pr(1, "fix: settle header on retry", paths=[])]) == []

    def test_unmerged_fixes_are_candidates_too(self) -> None:
        gaps = find_parity_gaps(
            [_pr(1, "fix: settle header on retry", paths=["go/pkg/s.go"], status="open")]
        )
        assert [g.pr.pr_number for g in gaps] == [1]

    def test_truncated_path_lists_stay_visible_on_the_gap(self) -> None:
        # The row is still surfaced, but it carries the warning that the
        # single-SDK conclusion rests on a partial file list.
        gaps = find_parity_gaps(
            [
                _pr(
                    1,
                    "fix: settle header on retry",
                    paths=["python/x402/s.py"],
                    truncated=True,
                )
            ]
        )
        assert gaps[0].pr.paths_truncated is True

    def test_most_incomplete_gaps_come_first(self) -> None:
        gaps = find_parity_gaps(
            [
                _pr(1, "fix: settle header missing on retry", paths=["python/x402/s.py"]),
                _pr(2, "fix: settle header missing on retry", paths=["typescript/src/s.ts"]),
                _pr(3, "fix: verify signature domain mismatch", paths=["go/pkg/v.go"]),
            ]
        )
        # #3 is missing from two SDKs; #1 and #2 only from go.
        assert gaps[0].pr.pr_number == 3
        assert len(gaps[0].missing_sdks) == 2
