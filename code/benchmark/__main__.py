"""CLI for the R0-A capture, arm execution, and blind packet workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from code.benchmark.capture import (
    canonical_json_bytes,
    load_frozen_capture,
    validate_artifact_dir,
)
from code.benchmark.codex_runner import CodexExecutor
from code.benchmark.digest import capture_live_digest
from code.benchmark.harness import (
    build_blind_packet,
    render_blind_review_markdown,
    run_arm,
    run_experiment_a,
    validate_formal_eligibility,
)
from code.benchmark.models import ExperimentConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SYSTEM = REPO_ROOT / "benchmarks/agent_friendliness/prompts/system-v1.md"
DEFAULT_TASK = REPO_ROOT / "benchmarks/agent_friendliness/prompts/task-v1.md"


def _read_required(path: str | Path, label: str) -> str:
    body = Path(path).read_text(encoding="utf-8").strip()
    if not body:
        raise ValueError(f"{label} must not be empty")
    return body


def _config(args: argparse.Namespace) -> ExperimentConfig:
    profile_path = Path(args.profile)
    if "example" in profile_path.name.lower() and not args.allow_example_profile:
        raise ValueError(
            "official runs cannot silently use the example profile; "
            "pass --allow-example-profile only for an informal smoke run"
        )
    return ExperimentConfig(
        model=args.model,
        effort=args.effort,
        system_instructions=_read_required(args.system, "system instructions"),
        task_prompt=_read_required(args.task, "task prompt"),
        prompt_version="r0-task-v1",
        personal_context=_read_required(profile_path, "private profile"),
        profile_version=args.profile_version,
        tool_policy="no-retrieval",
        randomization_seed=args.seed,
    )


def _add_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--capture-dir", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--profile-version", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", required=True)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--system", default=str(DEFAULT_SYSTEM))
    parser.add_argument("--task", default=str(DEFAULT_TASK))
    parser.add_argument("--allow-example-profile", action="store_true")
    parser.add_argument("--out", required=True)


def _write_blind(root: Path, edition: str, runs: dict, seed: int) -> Path:
    outputs = {arm: run.result for arm, run in runs.items()}
    if any(value is None for value in outputs.values()):
        raise RuntimeError("both arms must be schema-valid before blinding")
    packet = build_blind_packet(
        edition=edition,
        outputs={key: value for key, value in outputs.items() if value is not None},
        seed=seed,
    )
    root = validate_artifact_dir(root)
    blind_path = root / "blind" / "review.json"
    blind_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    blind_path.write_bytes(canonical_json_bytes(packet))
    blind_path.chmod(0o600)
    review_path = blind_path.with_name("review.md")
    review_path.write_text(render_blind_review_markdown(packet), encoding="utf-8")
    review_path.chmod(0o600)
    key_path = root / "private" / "unblinding.json"
    key_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    key_path.write_bytes(canonical_json_bytes(packet._mapping))
    key_path.chmod(0o600)
    return blind_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture_parser = subparsers.add_parser("capture")
    capture_parser.add_argument("--week", required=True)
    capture_parser.add_argument("--lang", default="ja")
    capture_parser.add_argument("--handles-config", required=True)
    capture_parser.add_argument("--topics-config", required=True)
    capture_parser.add_argument("--project")
    capture_parser.add_argument("--out", required=True)

    arm_parser = subparsers.add_parser("run-arm")
    _add_run_args(arm_parser)
    arm_parser.add_argument("--arm", choices=("H", "J"), required=True)

    pair_parser = subparsers.add_parser("run-pair")
    _add_run_args(pair_parser)

    review_parser = subparsers.add_parser("render-review")
    review_parser.add_argument("--packet", required=True)
    review_parser.add_argument("--out", required=True)

    args = parser.parse_args()
    if args.command == "render-review":
        from code.benchmark.models import BlindPacket

        packet = BlindPacket.model_validate_json(
            Path(args.packet).read_text(encoding="utf-8")
        )
        output = validate_artifact_dir(args.out)
        output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        output.write_text(render_blind_review_markdown(packet), encoding="utf-8")
        output.chmod(0o600)
        print(output)
        return 0
    if args.command == "capture":
        capture = capture_live_digest(
            week=args.week,
            lang=args.lang,
            handles_config=args.handles_config,
            topics_config=args.topics_config,
            artifact_dir=validate_artifact_dir(args.out),
            project=args.project,
        )
        print(capture.manifest_path)
        return 0

    capture = load_frozen_capture(args.capture_dir)
    validate_formal_eligibility(capture)
    config = _config(args)
    root = validate_artifact_dir(args.out)
    if args.command == "run-arm":
        run = run_arm(
            capture=capture,
            arm=args.arm,
            config=config,
            executor=CodexExecutor(),
            artifact_dir=root / "runs",
        )
        print(run.manifest_path)
        return 0 if run.manifest.status == "completed" else 1

    pair = run_experiment_a(
        capture=capture,
        config=config,
        executor_factory=CodexExecutor,
        artifact_dir=root / "runs",
    )
    blind_path = _write_blind(root, capture.edition, pair.runs, config.randomization_seed)
    print(
        json.dumps(
            {
                "capture": str(capture.manifest_path),
                "runs": {
                    arm: str(run.manifest_path) for arm, run in pair.runs.items()
                },
                "blind_packet": str(blind_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
