"""Tests for the cross-week PR field logic behind the survey views.

Pure functions, no Firestore: what we lock in is the mechanical rules
themselves — the snapshot-collapse order, the staleness anchors and
the exclusive 8-day threshold, the path-first SDK classification, and
the two-threshold counterpart match (strong title alone, weak title
plus a shared stem, never stem alone).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from code.schemas.pr import PRRecord
from code.survey.pr_field import (
    STALLED_AFTER_DAYS,
    find_parity_gaps,
    is_fix,
    latest_pr_snapshots,
    path_stems,
    sdk_dirs_touched,
    stalled_open_prs,
    title_match_tokens,
    title_similarity,
)

REPO = "x402-foundation/x402"
NOW = datetime(2026, 5, 26, 12, 0, tzinfo=timezone.utc)


def _rec(
    number: int,
    *,
    week: str = "2026-W21",
    status: str = "merged",
    kind: str = "merged",
    title: str = "fix: thing",
    author: str = "dev",
    touched_paths: tuple[str, ...] = (),
    merged_at: datetime | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    last_maintainer_activity_at: datetime | None = None,
    enriched_at: datetime | None = None,
    labels: tuple[str, ...] = (),
) -> PRRecord:
    return PRRecord(
        repo=REPO,
        pr_number=number,
        title=title,
        author=author,
        url=f"https://github.com/{REPO}/pull/{number}",
        week=week,
        status=status,
        kind=kind,
        merged_at=merged_at,
        created_at=created_at,
        updated_at=updated_at,
        labels=list(labels),
        touched_paths=list(touched_paths),
        last_maintainer_activity_at=last_maintainer_activity_at,
        enriched_at=enriched_at,
    )


class TestLatestPrSnapshots:
    def test_later_week_supersedes_earlier_snapshot(self) -> None:
        older = _rec(1, week="2026-W20", status="open", kind="open")
        newer = _rec(1, week="2026-W21", status="merged", kind="merged")
        [snap] = latest_pr_snapshots([newer, older])
        assert snap.status == "merged"
        assert snap.week == "2026-W21"

    def test_distinct_prs_all_survive(self) -> None:
        snaps = latest_pr_snapshots([_rec(1), _rec(2), _rec(3)])
        assert sorted(s.pr_number for s in snaps) == [1, 2, 3]

    def test_updated_at_breaks_ties_within_a_week(self) -> None:
        stale = _rec(1, updated_at=NOW - timedelta(days=3), status="open", kind="open")
        fresh = _rec(1, updated_at=NOW, status="merged")
        [snap] = latest_pr_snapshots([fresh, stale])
        assert snap.status == "merged"


class TestStalledOpenPRs:
    def test_threshold_is_exclusive_at_exactly_eight_days(self) -> None:
        boundary = _rec(
            1,
            status="open",
            last_maintainer_activity_at=NOW - timedelta(days=STALLED_AFTER_DAYS),
        )
        beyond = _rec(
            2,
            status="open",
            last_maintainer_activity_at=NOW
            - timedelta(days=STALLED_AFTER_DAYS, hours=1),
        )
        stalled = stalled_open_prs([boundary, beyond], now=NOW)
        assert [s.pr.pr_number for s in stalled] == [2]
        assert stalled[0].silent_days == STALLED_AFTER_DAYS

    def test_anchor_precedence_and_sort_longest_silence_first(self) -> None:
        responded = _rec(
            1,
            status="open",
            last_maintainer_activity_at=NOW - timedelta(days=12),
            created_at=NOW - timedelta(days=40),
            enriched_at=NOW,
        )
        never_responded = _rec(
            2,
            status="open",
            created_at=NOW - timedelta(days=20),
            enriched_at=NOW,
        )
        unenriched = _rec(
            3,
            status="open",
            created_at=NOW - timedelta(days=60),
            updated_at=NOW - timedelta(days=10),
        )
        stalled = stalled_open_prs([responded, never_responded, unenriched], now=NOW)
        assert [s.pr.pr_number for s in stalled] == [2, 1, 3]
        by_number = {s.pr.pr_number: s for s in stalled}
        assert by_number[1].anchor == "maintainer_response"
        assert by_number[2].anchor == "opened"
        assert by_number[2].silent_days == 20
        # un-enriched rows fall back to updated_at, not created_at
        assert by_number[3].anchor == "last_update"
        assert by_number[3].silent_days == 10

    def test_drafts_and_non_open_rows_are_skipped(self) -> None:
        draft = _rec(1, status="draft", created_at=NOW - timedelta(days=40))
        merged = _rec(2, status="merged", created_at=NOW - timedelta(days=40))
        fresh = _rec(
            3,
            status="open",
            last_maintainer_activity_at=NOW - timedelta(days=2),
        )
        assert stalled_open_prs([draft, merged, fresh], now=NOW) == []


class TestSdkClassification:
    def test_paths_classify_by_first_segment(self) -> None:
        pr = _rec(
            1,
            touched_paths=(
                "python/x402/verify.py",
                "python/tests/test_verify.py",
                "docs/spec.md",
            ),
        )
        assert sdk_dirs_touched(pr) == frozenset({"python"})

    def test_non_sdk_paths_do_not_classify(self) -> None:
        pr = _rec(1, touched_paths=("docs/spec.md", ".github/workflows/ci.yml"))
        assert sdk_dirs_touched(pr) == frozenset()

    def test_title_scope_stands_in_only_when_paths_are_absent(self) -> None:
        legacy = _rec(1, title="fix(go): handle nil facilitator")
        assert sdk_dirs_touched(legacy) == frozenset({"go"})
        # paths win over a contradicting title hint
        pathful = _rec(
            2, title="fix(go): handle nil facilitator", touched_paths=("python/a.py",)
        )
        assert sdk_dirs_touched(pathful) == frozenset({"python"})

    def test_bare_language_mention_mid_title_never_classifies(self) -> None:
        pr = _rec(1, title="fix flaky python test in CI")
        assert sdk_dirs_touched(pr) == frozenset()


class TestIsFix:
    def test_fix_words_and_labels_count(self) -> None:
        assert is_fix(_rec(1, title="fix: reject zero-amount voucher"))
        assert is_fix(_rec(2, title="Fixed race in settle loop"))
        assert is_fix(_rec(3, title="hotfix for nonce reuse"))
        assert is_fix(_rec(4, title="tighten validation", labels=("bug",)))

    def test_features_and_prefix_lookalikes_do_not(self) -> None:
        assert not is_fix(_rec(1, title="feat: add settle endpoint"))
        assert not is_fix(_rec(2, title="chore: prefix env vars"))


class TestTitleMatching:
    def test_tokens_drop_prefix_sdk_names_and_stopwords(self) -> None:
        tokens = title_match_tokens("fix(python): reject zero-amount voucher in the SDK")
        assert tokens == frozenset({"reject", "zero", "amount", "voucher"})

    def test_same_payload_across_sdk_phrasings_matches_fully(self) -> None:
        a = title_match_tokens("fix(python): reject zero-amount voucher")
        b = title_match_tokens("fix: reject zero-amount voucher (typescript)")
        assert title_similarity(a, b) == 1.0

    def test_empty_token_sets_never_match(self) -> None:
        assert title_similarity(frozenset(), frozenset({"x402"})) == 0.0


class TestPathStems:
    def test_stems_fold_test_affixes_and_drop_boilerplate(self) -> None:
        pr = _rec(
            1,
            touched_paths=(
                "python/x402/facilitator.py",
                "python/tests/test_facilitator.py",
                "python/x402/__init__.py",
                "go/go.mod",
            ),
        )
        assert path_stems(pr) == frozenset({"facilitator"})


class TestFindParityGaps:
    def _fix(self, number: int, sdk_path: str, **kw) -> PRRecord:
        kw.setdefault("title", "fix: reject zero-amount voucher")
        kw.setdefault("merged_at", NOW - timedelta(days=3))
        return _rec(number, touched_paths=(sdk_path,), **kw)

    def test_single_sdk_fix_missing_everywhere_lists_both_others(self) -> None:
        gap_fix = self._fix(1, "python/x402/verify.py")
        unrelated = _rec(
            2, title="feat: new dashboard", touched_paths=("typescript/site/app.ts",)
        )
        [gap] = find_parity_gaps([gap_fix, unrelated])
        assert gap.sdk == "python"
        assert gap.missing == ("go", "typescript")

    def test_strong_title_counterpart_covers_its_sdk(self) -> None:
        gap_fix = self._fix(1, "python/x402/verify.py")
        port = _rec(
            2,
            status="open",
            kind="open",
            title="fix(ts): reject zero-amount voucher",
            touched_paths=("typescript/packages/x402/src/client.ts",),
        )
        [gap] = find_parity_gaps([gap_fix, port])
        assert gap.missing == ("go",)

    def test_fully_ported_fix_is_not_a_gap(self) -> None:
        gap_fix = self._fix(1, "python/x402/verify.py")
        ts_port = self._fix(2, "typescript/packages/x402/src/verify.ts")
        go_port = self._fix(3, "go/pkg/x402/verify.go")
        assert find_parity_gaps([gap_fix, ts_port, go_port]) == []

    def test_weak_title_match_needs_a_shared_stem(self) -> None:
        gap_fix = self._fix(
            1, "python/x402/facilitator.py", title="fix: facilitator nonce reuse race"
        )
        # tokens {facilitator, nonce, reuse, race}; counterpart shares
        # only {facilitator, nonce} -> Jaccard 2/5 = 0.4: weak band.
        # Counterparts are open ports in flight, so they cover without
        # being gap candidates themselves.
        weak_with_stem = _rec(
            2,
            status="open",
            kind="open",
            title="fix: facilitator nonce checks",
            touched_paths=("go/pkg/x402/facilitator.go",),
        )
        [gap] = find_parity_gaps([gap_fix, weak_with_stem])
        assert gap.missing == ("typescript",)

        weak_without_stem = _rec(
            3,
            status="open",
            kind="open",
            title="fix: facilitator nonce checks",
            touched_paths=("go/pkg/x402/settle.go",),
        )
        [gap] = find_parity_gaps([gap_fix, weak_without_stem])
        assert gap.missing == ("go", "typescript")

    def test_shared_stem_alone_never_covers(self) -> None:
        gap_fix = self._fix(
            1, "python/x402/facilitator.py", title="fix: facilitator nonce reuse race"
        )
        refactor = _rec(
            2,
            title="chore: reorganise packages",
            touched_paths=("go/pkg/x402/facilitator.go",),
        )
        [gap] = find_parity_gaps([gap_fix, refactor])
        assert gap.missing == ("go", "typescript")

    def test_non_fixes_multi_sdk_and_open_rows_are_not_candidates(self) -> None:
        feature = _rec(
            1, title="feat: add settle endpoint", touched_paths=("python/a.py",)
        )
        multi_sdk = _rec(
            2,
            title="fix: sync error codes",
            touched_paths=("python/a.py", "go/b.go"),
        )
        still_open = _rec(
            3, status="open", title="fix: pending thing", touched_paths=("go/c.go",)
        )
        assert find_parity_gaps([feature, multi_sdk, still_open]) == []

    def test_newest_merge_first(self) -> None:
        old = self._fix(
            1,
            "python/x402/verify.py",
            title="fix: old python thing",
            merged_at=NOW - timedelta(days=30),
        )
        new = self._fix(
            2,
            "go/pkg/settle.go",
            title="fix: new go thing",
            merged_at=NOW - timedelta(days=1),
        )
        gaps = find_parity_gaps([old, new])
        assert [g.pr.pr_number for g in gaps] == [2, 1]
