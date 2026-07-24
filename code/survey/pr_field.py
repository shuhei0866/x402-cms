"""Cross-week PR field views for the survey — stalled PRs, parity gaps.

Two reconnaissance views (issue #17) distilled from the "x402 PR merge
process" field notes: once the whole PR index sits in one place, two
questions become mechanical lookups —

- **Stalled open PRs** — open PRs whose maintainers have been silent
  beyond `STALLED_AFTER_DAYS`. Feeds two curator moves: nudging one's
  own PR (only when new facts justify it) and picking someone else's
  stalled work up as a port or an audit.
- **Cross-SDK parity gaps** — merged fixes that landed in exactly one
  SDK directory (go / python / typescript) with no matching change in
  the others. The "stop waiting, become the auditor" move: porting
  such a fix is the kind of contribution mass-produced AI PRs don't
  make.

Both views stay retrieval + mechanical matching, like the rest of the
survey: paths and title tokens in, lists out. No LLM sees any of this;
observation and hypothesis remain the curator's job.

Unlike the week-scoped readers in `code.renderers.digest.readers`,
these views need the whole indexed corpus: a PR stalls across weeks,
and a fix's counterpart may trail it by months. `read_all_pr_records`
therefore streams the full `source_data` collection (hundreds of rows
at current volume) and `latest_pr_snapshots` collapses the per-week
snapshots into each PR's latest known state.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from google.cloud import firestore

from code.renderers.digest import COLLECTION
from code.schemas.pr import PRRecord
from code.utils.firestore import build_client

# The field notes' measured first-response times: median 1.5 days,
# maximum 8 days. Silence beyond the observed maximum is what we call
# stalled; the comparison is exclusive (> 8 days).
STALLED_AFTER_DAYS = 8

# Top-level SDK directories in the tracked monorepo. A path classifies
# a PR into the SDK its first segment names; docs/, examples/ and the
# like simply don't classify.
SDK_DIRS: tuple[str, ...] = ("go", "python", "typescript")

# Thresholds for counterpart matching, chosen to trade toward noise
# over blindness: a missed counterpart costs the curator seconds of
# scanning, a phantom counterpart silently hides a real gap. A strong
# title match stands alone; a weak one needs a shared filename stem;
# stem overlap alone never covers (any wide refactor touches many
# stems).
TITLE_MATCH_JACCARD = 0.5
TITLE_MATCH_JACCARD_WEAK = 0.25


def read_all_pr_records(
    project: str | None = None,
    *,
    client: firestore.Client | None = None,
) -> list[PRRecord]:
    """Every PR row in `source_data`, across all weeks and kinds.

    Legacy rows predate `status` / `kind`; they were written by the
    merged-only indexer, so both default to "merged" (the same
    backward-compatibility rule `read_week` applies). Payloads are
    copied before normalising so a document shared with another reader
    is never mutated.
    """
    fs = build_client(client, project)
    records: list[PRRecord] = []
    for doc in fs.collection(COLLECTION).stream():
        data = dict(doc.to_dict() or {})
        data.setdefault("status", "merged")
        data.setdefault("kind", "merged")
        records.append(PRRecord.model_validate(data))
    return records


def _aware(ts: datetime | None) -> datetime | None:
    """Coerce a naive timestamp (legacy rows) to UTC so arithmetic works."""
    if ts is not None and ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


_FLOOR = datetime.min.replace(tzinfo=timezone.utc)


def latest_pr_snapshots(records: list[PRRecord]) -> list[PRRecord]:
    """Collapse weekly snapshots into one row per (repo, pr_number).

    Zero-padded `YYYY-Www` labels sort chronologically as strings;
    `updated_at` breaks (theoretical) ties within a week. The latest
    snapshot carries the PR's current known state — an open row from
    W20 superseded by a merged row in W21 reads as merged.
    """
    best: dict[tuple[str, int], PRRecord] = {}
    for record in records:
        key = (record.repo, record.pr_number)
        current = best.get(key)
        if current is None or (record.week, _aware(record.updated_at) or _FLOOR) > (
            current.week,
            _aware(current.updated_at) or _FLOOR,
        ):
            best[key] = record
    return list(best.values())


StalledAnchor = Literal["maintainer_response", "opened", "last_update"]


@dataclass(frozen=True)
class StalledPR:
    pr: PRRecord
    silent_days: int
    anchor: StalledAnchor


def stalled_open_prs(
    records: list[PRRecord],
    *,
    now: datetime,
    threshold_days: int = STALLED_AFTER_DAYS,
) -> list[StalledPR]:
    """Open PRs silent beyond the threshold, longest silence first.

    Silence anchors on the strongest evidence each row carries:

    - `last_maintainer_activity_at` when enrichment recorded a real
      maintainer response ("maintainer_response");
    - `created_at` when enrichment ran and found none — the PR has
      waited its whole life ("opened");
    - `updated_at` (falling back to `created_at`) for un-enriched
      legacy rows ("last_update") — an under-estimate, since any push
      or drive-by comment refreshes it, so legacy rows err toward NOT
      flagging.

    Draft rows are skipped: a draft is not requesting review, so
    maintainer silence there is not a signal.
    """
    out: list[StalledPR] = []
    for record in records:
        if record.status != "open":
            continue
        anchor: StalledAnchor
        if record.last_maintainer_activity_at is not None:
            anchor_ts, anchor = record.last_maintainer_activity_at, "maintainer_response"
        elif record.enriched_at is not None:
            anchor_ts, anchor = record.created_at, "opened"
        else:
            anchor_ts, anchor = record.updated_at or record.created_at, "last_update"
        anchor_ts = _aware(anchor_ts)
        if anchor_ts is None:
            continue
        silence = now - anchor_ts
        if silence > timedelta(days=threshold_days):
            out.append(StalledPR(pr=record, silent_days=silence.days, anchor=anchor))
    out.sort(key=lambda s: (-s.silent_days, s.pr.repo, s.pr.pr_number))
    return out


# --- cross-SDK parity matching -----------------------------------------

_FIX_WORD_RE = re.compile(r"\b((hot)?fix(e[sd])?|bug(fix)?)\b", re.I)

_CONVENTIONAL_PREFIX_RE = re.compile(
    r"^\s*(fix|feat|feature|chore|refactor|perf|docs?|test|tests|ci|cd|build"
    r"|style|release|revert)(\([^)]*\))?\s*!?\s*:\s*",
    re.I,
)
_SCOPE_RE = re.compile(r"^\s*[a-z]+\s*\(([^)]*)\)\s*!?\s*:", re.I)
_BRACKET_RE = re.compile(r"^\s*\[([^\]]*)\]")
_TOKEN_RE = re.compile(r"[a-z0-9]+")

_SDK_TITLE_HINTS = {
    "typescript": "typescript",
    "ts": "typescript",
    "python": "python",
    "py": "python",
    "go": "go",
    "golang": "go",
}

_STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "of", "in", "on", "for", "to",
        "with", "from", "when", "into", "is", "are", "be", "by", "at",
        "as", "not", "no",
    }
)
_SDK_TOKENS = frozenset(
    {"typescript", "ts", "javascript", "js", "python", "py", "go", "golang", "sdk"}
)

# Stems that recur in every package — matching on them would let any
# refactor "cover" any fix. The project name itself is in the list for
# the same reason.
_STEM_STOPLIST = frozenset(
    {
        "index", "main", "mod", "init", "__init__", "readme", "changelog",
        "license", "package", "setup", "types", "utils", "util", "test",
        "tests", "conftest", "x402", "go", "makefile", "dockerfile",
    }
)


def is_fix(pr: PRRecord) -> bool:
    """Mechanical fix detection: the title says fix/bug, or a label does."""
    if _FIX_WORD_RE.search(pr.title):
        return True
    return any("bug" in label.lower() or "fix" in label.lower() for label in pr.labels)


def _sdk_hints_from_title(title: str) -> frozenset[str]:
    match = _SCOPE_RE.match(title) or _BRACKET_RE.match(title)
    if not match:
        return frozenset()
    hits = set()
    for raw in re.split(r"[,/\s]+", match.group(1).lower()):
        mapped = _SDK_TITLE_HINTS.get(raw)
        if mapped:
            hits.add(mapped)
    return frozenset(hits)


def sdk_dirs_touched(pr: PRRecord) -> frozenset[str]:
    """SDK directories a PR belongs to.

    Paths are authoritative: each path's first segment is matched
    against `SDK_DIRS`, and non-SDK paths (docs/, examples/, .github/)
    simply don't classify. Only when a row carries no paths at all
    (legacy rows predating enrichment) does a structured title hint — a
    conventional scope like `fix(python): ...` or a leading `[go]` tag
    — stand in. A bare language mention mid-sentence never classifies;
    that would drift from mechanical matching toward guessing.
    """
    if pr.touched_paths:
        top = {path.split("/", 1)[0] for path in pr.touched_paths}
        return frozenset(d for d in SDK_DIRS if d in top)
    return _sdk_hints_from_title(pr.title)


def title_match_tokens(title: str) -> frozenset[str]:
    """Normalised token set used for cross-SDK title matching.

    Lowercase, conventional prefix stripped, stopwords / SDK names /
    single characters dropped — so `fix(python): reject zero-amount
    voucher` and `fix: reject zero-amount voucher (typescript)` compare
    on the shared payload {reject, zero, amount, voucher}.
    """
    stripped = _CONVENTIONAL_PREFIX_RE.sub("", title.lower())
    return frozenset(
        token
        for token in _TOKEN_RE.findall(stripped)
        if len(token) > 1 and token not in _STOPWORDS and token not in _SDK_TOKENS
    )


def title_similarity(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard similarity of two token sets; 0.0 when either is empty."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def path_stems(pr: PRRecord) -> frozenset[str]:
    """Filename stems for the weak leg of counterpart matching.

    `python/x402/facilitator.py` and `typescript/.../facilitator.ts`
    share the stem `facilitator` even though the directory layouts
    differ per SDK. Test-file affixes are folded in (`test_verify.py`
    -> `verify`), and boilerplate stems are dropped via the stoplist.
    """
    stems: set[str] = set()
    for path in pr.touched_paths:
        base = path.rsplit("/", 1)[-1].lower()
        stem = base.split(".", 1)[0].replace("-", "_")
        stem = stem.removeprefix("test_").removesuffix("_test")
        if len(stem) > 2 and stem not in _STEM_STOPLIST:
            stems.add(stem)
    return frozenset(stems)


@dataclass(frozen=True)
class ParityGap:
    pr: PRRecord
    sdk: str
    missing: tuple[str, ...]


def find_parity_gaps(
    snapshots: list[PRRecord],
    *,
    sdk_dirs: tuple[str, ...] = SDK_DIRS,
) -> list[ParityGap]:
    """Merged single-SDK fixes with no counterpart in some other SDK.

    A candidate is a latest snapshot that is merged, classifies into
    exactly one SDK directory, and looks like a fix (`is_fix`). For
    each of the other SDKs, a counterpart is any indexed PR — any
    status, since an open port in flight already covers the gap for
    candidate-picking purposes — that touches that SDK and matches the
    candidate on:

    - normalised title Jaccard >= `TITLE_MATCH_JACCARD`, or
    - Jaccard >= `TITLE_MATCH_JACCARD_WEAK` plus a shared filename stem.

    SDKs with no counterpart land in `missing`; a candidate with a
    non-empty `missing` is a gap. Newest merged first.
    """
    classified = [
        (r, sdk_dirs_touched(r), title_match_tokens(r.title), path_stems(r))
        for r in snapshots
    ]
    out: list[ParityGap] = []
    for record, sdks, tokens, stems in classified:
        if record.status != "merged" or len(sdks) != 1 or not is_fix(record):
            continue
        sdk = next(iter(sdks))
        missing: list[str] = []
        for other in sdk_dirs:
            if other == sdk:
                continue
            covered = any(
                _covers(tokens, stems, other, cp_sdks, cp_tokens, cp_stems)
                for cp, cp_sdks, cp_tokens, cp_stems in classified
                if cp is not record
            )
            if not covered:
                missing.append(other)
        if missing:
            out.append(ParityGap(pr=record, sdk=sdk, missing=tuple(missing)))
    out.sort(key=lambda g: (g.pr.repo, g.pr.pr_number))
    out.sort(key=lambda g: _aware(g.pr.merged_at) or _FLOOR, reverse=True)
    return out


def _covers(
    tokens: frozenset[str],
    stems: frozenset[str],
    target_sdk: str,
    counterpart_sdks: frozenset[str],
    counterpart_tokens: frozenset[str],
    counterpart_stems: frozenset[str],
) -> bool:
    if target_sdk not in counterpart_sdks:
        return False
    similarity = title_similarity(tokens, counterpart_tokens)
    if similarity >= TITLE_MATCH_JACCARD:
        return True
    return similarity >= TITLE_MATCH_JACCARD_WEAK and bool(stems & counterpart_stems)
