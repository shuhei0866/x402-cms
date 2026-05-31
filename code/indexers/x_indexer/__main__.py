"""CLI entrypoint: `python -m code.indexers.x_indexer`.

Reads tracked handles + `X_BEARER_TOKEN`, runs `run_for_week` for
either an explicit `--week` or the previous ISO week, and prints the
summary JSON to stdout. `--dry-run` mirrors the github indexer:
fetch + report, no Firestore write.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import httpx

from code.indexers.x_indexer.loader import load_tracked_handles
from code.indexers.x_indexer.orchestrator import run_for_week
from code.utils.dates import resolve_target_week


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch tweets from tracked X handles into Firestore.",
    )
    parser.add_argument(
        "--week",
        default=None,
        help=(
            "ISO week label, e.g. '2026-W19'. Defaults to the ISO week "
            "of (today - 7 days), i.e. the previous week."
        ),
    )
    parser.add_argument(
        "--current",
        action="store_true",
        help=(
            "Target the in-progress ISO week instead of the previous "
            "one. Used by the daily scheduler to refresh the current "
            "week's digest; ignored when --week is given."
        ),
    )
    parser.add_argument(
        "--handles-config",
        default="config/tracked_handles.yaml",
        help="Path to the YAML file listing tracked handles.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and print results to stdout, but do not write to Firestore.",
    )
    args = parser.parse_args()

    bearer = os.getenv("X_BEARER_TOKEN")
    if not bearer:
        print(
            "X_BEARER_TOKEN is not set; export it via .env or env var "
            "before running the indexer.",
            file=sys.stderr,
        )
        return 2

    handles = load_tracked_handles(args.handles_config)
    if not handles:
        print(
            f"No handles found in {args.handles_config}; nothing to do.",
            file=sys.stderr,
        )
        return 0

    week = resolve_target_week(args.week, args.current)
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    print(
        f"Fetching tweets for {len(handles)} handle(s) over {week} "
        f"(project: {project or 'ADC default'}, dry_run={args.dry_run}).",
        file=sys.stderr,
    )

    with httpx.Client(timeout=30.0) as client:
        result = run_for_week(
            week=week,
            handles=handles,
            bearer=bearer,
            client=client,
            project=project,
            dry_run=args.dry_run,
        )

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
