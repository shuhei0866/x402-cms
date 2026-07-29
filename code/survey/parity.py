"""Cross-SDK parity matching: a fix landed in one SDK, not the others.

x402 ships the same protocol three times over — `typescript/`,
`python/`, `go/`. A bug found in one of them is usually a bug in all
three, but the fix only lands where whoever hit it was working. That
leaves a standing supply of small, verifiable, unglamorous work: port
the fix sideways. It is also the kind of contribution a maintainer can
tell apart from AI-generated volume at a glance, because it starts from
a change the project already accepted.

Finding those gaps needs no model. Two mechanical signals do it:

- **the paths a PR touched** say which SDK it lives in. A PR confined
  to one SDK directory is a candidate; one spanning two already carries
  its own port.
- **the title** says what the change is about. A fix and its port are
  written by different people at different times, but they describe the
  same symptom, so their titles share their rare words — `settle`,
  `header`, `retry` — while differing on the SDK name and on the verbs
  every commit uses. Strip the second group, compare what is left as
  sets, and counterparts surface without anything reading the diff.

Both signals are approximations, and neither is asked to decide
anything. The output is a candidate list for the human to judge — the
same contract the rest of the survey keeps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from code.schemas.pr import PRRecord

SDKS: tuple[str, ...] = ("typescript", "python", "go")

SDK_DIRECTORY_ALIASES: dict[str, str] = {
    "typescript": "typescript",
    "ts": "typescript",
    # The JS and TS packages share a runtime and a release train, so a
    # JS-only fix raises the same "did python and go get this?" question.
    "javascript": "typescript",
    "js": "typescript",
    "python": "python",
    "py": "python",
    "go": "go",
    "golang": "go",
}

PARITY_SIMILARITY_THRESHOLD = 0.4
"""Jaccard floor on the two token sets.

Set from what real counterpart titles look like: "fix: settle response
header not set on 402 retry" against "fix(python): settle header
missing on retry" reduces to {402, header, response, retry, settle} and
{header, missing, retry, settle}, sharing 3 of a 6-token union — 0.50,
comfortably clear of the floor. Lower and unrelated fixes that happen
to share one common noun start pairing up; higher and a port worded
more freely than its original stops matching.
"""

PARITY_MIN_SHARED_TOKENS = 2
"""One word in common is a coincidence, not a port."""

SAMPLE_PATHS = 3

_CONVENTIONAL_PREFIX_RE = re.compile(r"^\s*[a-z]+(?:\(([^)]*)\))?!?:\s*", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[a-z0-9]+")

_FIX_TITLE_RE = re.compile(
    r"\b(fix|fixes|fixed|fixing|bug|bugfix|hotfix|regression|broken|crash)\b",
    re.IGNORECASE,
)
_FIX_LABEL_RE = re.compile(r"\b(bug|fix|regression)\b", re.IGNORECASE)

STOPWORDS = frozenset(
    {
        # Conventional-commit types and the verbs every PR title uses.
        # They carry no subject, so leaving them in would make any two
        # fixes look 30% alike before the real words are compared.
        "fix", "fixes", "fixed", "fixing", "bug", "bugfix", "hotfix",
        "feat", "feature", "chore", "refactor", "docs", "doc", "test",
        "tests", "ci", "build", "style", "perf", "revert",
        "add", "adds", "added", "update", "updates", "updated", "remove",
        "removes", "removed", "support", "handle", "handling", "use",
        "using", "make", "makes", "allow", "improve", "correct", "bump",
        "ensure", "avoid", "prevent", "set", "return", "returns",
        # SDK names — precisely what a change and its port disagree on,
        # so keeping them would penalise exactly the pairs we want.
        "typescript", "ts", "javascript", "js", "python", "py", "go",
        "golang", "sdk", "sdks", "pkg", "package", "packages", "lib",
        "client", "server", "example", "examples",
        # English function words.
        "a", "an", "the", "to", "in", "on", "of", "for", "and", "or",
        "with", "when", "not", "no", "is", "are", "be", "been", "from",
        "at", "by", "into", "if", "it", "its", "this", "that", "as",
        "but", "should", "would", "we", "do", "does", "was", "were",
        "all", "any", "so", "than", "then", "there", "via",
    }
)


@dataclass
class ParityGap:
    """A single-SDK fix with no sibling change found in another SDK."""

    pr: PRRecord
    sdk: str
    missing_sdks: list[str]
    """SDKs with nothing that looks like this change."""

    matched_sdks: list[str] = field(default_factory=list)
    """SDKs that do appear to have it — a partly-ported fix is still a
    gap for whichever SDK is left out, and saying which ones matched
    keeps the row honest about how much is actually missing."""

    sample_paths: list[str] = field(default_factory=list)


def _normalise_segment(segment: str) -> str:
    seg = segment.strip().lower()
    if seg.startswith("x402-"):
        seg = seg[len("x402-") :]
    if seg.endswith("-sdk"):
        seg = seg[: -len("-sdk")]
    return seg


def sdks_touched(paths: list[str]) -> set[str]:
    """Which SDK families a set of changed paths belongs to.

    Matched on directory *segments* rather than a leading prefix, so
    `python/x402/exact.py` and `examples/python/servers/fastapi/main.py`
    both resolve to `python` without the caller enumerating every layout
    the monorepo has grown. The file name itself is excluded — a
    `docs/python.md` is documentation about the SDK, not a change to it.
    """
    found: set[str] = set()
    for path in paths:
        for segment in path.split("/")[:-1]:
            sdk = SDK_DIRECTORY_ALIASES.get(_normalise_segment(segment))
            if sdk:
                found.add(sdk)
    return found


def title_tokens(title: str) -> set[str]:
    """Reduce a PR title to the words that identify what it is about.

    The conventional-commit type is dropped but its scope is kept —
    `fix(facilitator):` says something real about the subject, whereas
    `fix:` says only that it is a fix. What survives is lowercased,
    split on non-alphanumerics, and filtered against `STOPWORDS`.
    """
    stripped = _CONVENTIONAL_PREFIX_RE.sub(
        lambda m: f"{m.group(1) or ''} ", title, count=1
    )
    return {
        token
        for token in _TOKEN_RE.findall(stripped.lower())
        if len(token) > 1 and token not in STOPWORDS
    }


def is_fix(pr: PRRecord) -> bool:
    """Does this PR present itself as a bug fix?

    Title wording first, labels second. Deliberately generous: a missed
    fix costs a porting opportunity, whereas a feature slipping into the
    list costs the curator one line of reading.
    """
    if _FIX_TITLE_RE.search(pr.title):
        return True
    return any(_FIX_LABEL_RE.search(label) for label in pr.labels)


def titles_match(
    left: set[str],
    right: set[str],
    *,
    threshold: float = PARITY_SIMILARITY_THRESHOLD,
    min_shared: int = PARITY_MIN_SHARED_TOKENS,
) -> bool:
    """Do two reduced titles look like the same change, twice?"""
    shared = left & right
    if len(shared) < min_shared:
        return False
    union = left | right
    if not union:
        return False
    return len(shared) / len(union) >= threshold


def _paths_in_sdk(paths: list[str], sdk: str) -> list[str]:
    return [p for p in paths if sdks_touched([p]) == {sdk}]


def find_parity_gaps(
    prs: list[PRRecord],
    *,
    threshold: float = PARITY_SIMILARITY_THRESHOLD,
    min_shared: int = PARITY_MIN_SHARED_TOKENS,
) -> list[ParityGap]:
    """List single-SDK fixes with no counterpart among `prs`.

    The counterpart pool is every single-SDK PR given, not only the
    fixes: a port may well be titled `feat:` or `chore:` by whoever
    carried it across. PRs with no indexed paths sit out entirely —
    absent data is not evidence of a gap — and the caller reports how
    many those were.

    Most-incomplete first, then newest.
    """
    scoped: list[tuple[PRRecord, str, set[str]]] = []
    for pr in prs:
        if not pr.changed_paths:
            continue
        touched = sdks_touched(pr.changed_paths)
        # Zero means the PR never entered an SDK directory (specs, docs,
        # CI); two or more means it already spans the SDKs it needs to.
        if len(touched) != 1:
            continue
        scoped.append((pr, next(iter(touched)), title_tokens(pr.title)))

    gaps: list[ParityGap] = []
    for pr, sdk, tokens in scoped:
        if not is_fix(pr):
            continue
        matched = {
            other_sdk
            for other_pr, other_sdk, other_tokens in scoped
            if other_sdk != sdk
            and titles_match(
                tokens, other_tokens, threshold=threshold, min_shared=min_shared
            )
        }
        missing = [s for s in SDKS if s != sdk and s not in matched]
        if not missing:
            continue
        gaps.append(
            ParityGap(
                pr=pr,
                sdk=sdk,
                missing_sdks=missing,
                matched_sdks=sorted(matched),
                sample_paths=_paths_in_sdk(pr.changed_paths, sdk)[:SAMPLE_PATHS],
            )
        )
    gaps.sort(key=lambda g: (-len(g.missing_sdks), -g.pr.pr_number))
    return gaps
