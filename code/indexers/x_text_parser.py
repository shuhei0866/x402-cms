"""X-post text parsers.

`parse_pr_references` is the single cross-reference primitive: it
extracts canonical `owner/repo#N` tokens from tweet text. Render-time
PR/post joins consume this field; nothing else in the pipeline reads
the raw tweet text for cross-references.
"""

from __future__ import annotations

import re

# Pull-request URL pattern. The `/pull/` segment is required, which
# excludes /issues/, /commit/, /tree/, and repo-root links — those
# would carry different semantics that we deliberately do not promote
# into the PR-reference set.
#
# Trailing characters after the PR number are tolerated (query strings,
# fragments, sentence punctuation) by matching the digit run greedily
# and stopping there; everything after the number is allowed to be
# anything but the parser does not include it in the output.
_PR_URL_RE = re.compile(
    r"https?://github\.com/([\w.-]+)/([\w.-]+)/pull/(\d+)",
    re.IGNORECASE,
)


def parse_pr_references(text: str) -> list[str]:
    """Return canonical `owner/repo#N` tokens found in `text`.

    Order is first-appearance; duplicates are removed while preserving
    that order, so renderers can quote the same sequence the tweet did.
    """
    seen: set[str] = set()
    refs: list[str] = []
    for match in _PR_URL_RE.finditer(text):
        owner, repo, number = match.group(1), match.group(2), match.group(3)
        token = f"{owner}/{repo}#{number}"
        if token in seen:
            continue
        seen.add(token)
        refs.append(token)
    return refs
