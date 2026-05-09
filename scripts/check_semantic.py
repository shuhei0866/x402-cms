#!/usr/bin/env python
"""Layer 2 — LLM-based semantic guard for x402-cms.

Detects subtle leaks regex cannot catch: attribution semantics,
meta-commentary, implicit professional context, peer references.

Loads the system prompt from prompts/semantic_check_system.md (gitignored).
Without that prompt or without ANTHROPIC_API_KEY, this hook is a no-op.

Decision schema (LLM output):
    {"decision": "OK" | "WARN" | "BLOCK", "reasons": [...]}

Bypass when intentional: git commit --no-verify
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROMPT_FILE = Path("prompts/semantic_check_system.md")
DIFF_CHAR_CAP = 30_000
MODEL = "claude-haiku-4-5"
MAX_TOKENS = 600


def _get_staged_diff() -> str:
    result = subprocess.run(
        ["git", "diff", "--cached", "--diff-filter=AM"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _parse_decision(text: str) -> dict:
    """Best-effort JSON parsing tolerant of fenced code blocks."""
    text = text.strip()
    if "```" in text:
        for block in text.split("```"):
            block = block.strip()
            if block.startswith("json"):
                block = block[4:].strip()
            if not block:
                continue
            try:
                return json.loads(block)
            except json.JSONDecodeError:
                continue
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"decision": "WARN", "reasons": [f"non-JSON LLM output: {text[:200]}"]}


def main() -> int:
    if not PROMPT_FILE.exists():
        return 0

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set; skipping Layer 2 semantic check.")
        return 0

    diff = _get_staged_diff()
    if not diff.strip():
        return 0

    try:
        import anthropic
    except ImportError:
        print("anthropic SDK not installed; skipping Layer 2.")
        return 0

    system_prompt = PROMPT_FILE.read_text(encoding="utf-8")

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": (
                    "Review the following staged git diff against the policy. "
                    'Output JSON only: {"decision": "OK"|"WARN"|"BLOCK", "reasons": [...]}.'
                    f"\n\nDiff:\n\n{diff[:DIFF_CHAR_CAP]}"
                ),
            }
        ],
    )

    text_blocks = [b.text for b in response.content if hasattr(b, "text")]
    text = "\n".join(text_blocks)
    result = _parse_decision(text)
    decision = (result.get("decision") or "OK").upper()
    reasons = result.get("reasons") or []

    if decision == "BLOCK":
        print("❌ Layer 2 — semantic guard: BLOCK")
        for r in reasons:
            print(f"  - {r}")
        print("\nBypass when intentional: git commit --no-verify")
        return 1
    if decision == "WARN":
        print("⚠️  Layer 2 — semantic guard: WARN (commit will proceed)")
        for r in reasons:
            print(f"  - {r}")
        return 0
    print("✓ Layer 2 — semantic guard: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
