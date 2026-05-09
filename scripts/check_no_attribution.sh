#!/usr/bin/env bash
# Layer 1 — Regex pattern guard for the public x402-cms repo.
#
# This script ships with NO patterns by design. Patterns are loaded from
# .git/hooks/personal-patterns.local.txt (gitignored). Add any private
# patterns you want to block in your local commits there.
#
# Without that file, this hook is a no-op.
#
# Error messages do not reveal which pattern matched — only the count —
# because the patterns themselves can be sensitive.
#
# Bypass when intentional: git commit --no-verify

set -euo pipefail

LOCAL_FILE=".git/hooks/personal-patterns.local.txt"

if [ ! -f "$LOCAL_FILE" ]; then
  exit 0
fi

PATTERNS=()
while IFS= read -r line; do
  if [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]]; then
    continue
  fi
  PATTERNS+=("$line")
done < "$LOCAL_FILE"

if [ ${#PATTERNS[@]} -eq 0 ]; then
  exit 0
fi

STAGED_DIFF=$(git diff --cached --diff-filter=AM | grep -E '^\+[^+]' || true)

if [ -z "$STAGED_DIFF" ]; then
  exit 0
fi

ERRORS=0
for pattern in "${PATTERNS[@]}"; do
  if echo "$STAGED_DIFF" | grep -iEq "$pattern"; then
    echo "❌ Layer 1 — pattern matched: (private)"
    ERRORS=$((ERRORS + 1))
  fi
done

if [ "$ERRORS" -gt 0 ]; then
  echo ""
  echo "Layer 1 caught $ERRORS pattern(s) that look like private information."
  echo "Bypass when intentional: git commit --no-verify"
  exit 1
fi

exit 0
