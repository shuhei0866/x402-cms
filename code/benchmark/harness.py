"""Experiment A orchestration, validation, and blind packet generation."""

from __future__ import annotations

import json
import random
import re
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from code.benchmark.capture import (
    canonical_json_bytes,
    capture_edition,
    sha256_digest,
    validate_artifact_dir,
)
from code.benchmark.codex_runner import build_runner_prompt
from code.benchmark.models import (
    BenchmarkResult,
    BenchmarkRun,
    BlindPacket,
    BlindResponse,
    ExperimentConfig,
    ExperimentPair,
    FrozenCapture,
    ResultChecks,
    RunManifest,
    RunMetrics,
    RunRequest,
    VerticalSliceResult,
)


class IneligibleEditionError(ValueError):
    pass


class PairValidationError(ValueError):
    pass


class Executor(Protocol):
    def execute(self, request: RunRequest) -> Mapping[str, Any]: ...


def evaluate_result(result: BenchmarkResult, *, representation: str) -> ResultChecks:
    urls = [str(url) for item in result.top_items for url in item.evidence_urls]
    normalised_ids = [item.id.strip().casefold() for item in result.top_items]
    return ResultChecks(
        evidence_urls_present=all(url in unescape(representation) for url in urls),
        duplicate_recommendation_count=len(normalised_ids) - len(set(normalised_ids)),
    )


def validate_formal_eligibility(capture: FrozenCapture) -> None:
    if capture.edition == "2026-W28":
        raise IneligibleEditionError("2026-W28 is contaminated and excluded")
    if set(capture.arms) != {"H", "J"}:
        raise IneligibleEditionError("both H and J arms are required")
    if any(arm.source_snapshot_digest != capture.source_snapshot_digest for arm in capture.arms.values()):
        raise IneligibleEditionError("arms do not share the frozen source snapshot")
    if isinstance(capture.snapshot, dict) and capture.snapshot.get("week") not in {
        None,
        capture.edition,
    }:
        raise IneligibleEditionError("capture edition differs from snapshot week")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _manifest_path(artifact_dir: Path, arm: str) -> Path:
    return artifact_dir / arm / "manifest.json"


def run_arm(
    *,
    capture: FrozenCapture,
    arm: str,
    config: ExperimentConfig,
    executor: Executor,
    artifact_dir: str | Path,
) -> BenchmarkRun:
    if arm not in {"H", "J"}:
        raise ValueError("arm must be H or J")
    artifact_root = validate_artifact_dir(artifact_dir)
    representation = capture.representations[arm]
    request = RunRequest(
        arm=arm,  # type: ignore[arg-type]
        model=config.model,
        effort=config.effort,
        system_instructions=config.system_instructions,
        task_prompt=config.task_prompt,
        personal_context=config.personal_context,
        representation=representation,
        tool_policy=config.tool_policy,
    )
    runner_input = build_runner_prompt(request)
    started_at = _utc_now()
    started_monotonic = time.monotonic()
    status = "completed"
    failure_reason: str | None = None
    result: BenchmarkResult | None = None
    response: Mapping[str, Any] = {}
    try:
        response = executor.execute(request)
        result = BenchmarkResult.model_validate_json(str(response.get("output", "")))
        checks = evaluate_result(result, representation=representation)
        if int(response.get("tool_calls", 0)) > 0:
            status = "failed"
            failure_reason = "tool policy violation: model called a tool"
            result = None
    except TimeoutError as exc:
        status = "timeout"
        failure_reason = str(exc) or "90-second timeout"
        checks = ResultChecks(
            response_schema_valid=False,
            exactly_three_items_valid=False,
            evidence_urls_present=False,
            duplicate_recommendation_count=0,
        )
    except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
        status = "failed"
        failure_reason = f"{type(exc).__name__}: {exc}"
        checks = ResultChecks(
            response_schema_valid=False,
            exactly_three_items_valid=False,
            evidence_urls_present=False,
            duplicate_recommendation_count=0,
        )
    except Exception as exc:
        status = "failed"
        failure_reason = f"{type(exc).__name__}: {exc}"
        checks = ResultChecks(
            response_schema_valid=False,
            exactly_three_items_valid=False,
            evidence_urls_present=False,
            duplicate_recommendation_count=0,
        )
    completed_at = _utc_now()
    elapsed_ms = round((time.monotonic() - started_monotonic) * 1000)

    manifest = RunManifest(
        schema_version="r0-run-manifest-v1",
        run_id=f"{capture.edition}-{arm}-{started_at.strftime('%Y%m%dT%H%M%S%fZ')}",
        experiment="A",
        status=status,  # type: ignore[arg-type]
        edition=capture.edition,
        arm=arm,  # type: ignore[arg-type]
        model=config.model,
        effort=config.effort,
        prompt_version=config.prompt_version,
        prompt_digest=sha256_digest(config.task_prompt),
        system_instructions_digest=sha256_digest(config.system_instructions),
        profile_version=config.profile_version,
        profile_digest=sha256_digest(config.personal_context),
        source_snapshot_digest=capture.source_snapshot_digest,
        representation_digest=capture.arms[arm].body_digest,
        runner_input_digest=sha256_digest(runner_input),
        codex_cli_version=response.get("codex_cli_version"),
        randomization_seed=config.randomization_seed,
        started_at=started_at,
        completed_at=completed_at,
        tool_policy=config.tool_policy,
        failure_reason=failure_reason,
        metrics=RunMetrics(
            input_tokens=response.get("input_tokens"),
            cached_input_tokens=response.get("cached_input_tokens"),
            output_tokens=response.get("output_tokens"),
            reasoning_output_tokens=response.get("reasoning_output_tokens"),
            input_bytes=len(runner_input.encode("utf-8")),
            representation_bytes=len(representation.encode("utf-8")),
            wall_clock_ms=elapsed_ms,
            model_calls=int(response.get("model_calls", 0)),
            tool_calls=int(response.get("tool_calls", 0)),
            **checks.model_dump(),
        ),
    )
    path = _manifest_path(artifact_root, arm)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_bytes(canonical_json_bytes(manifest))
    path.chmod(0o600)
    if response.get("events"):
        events_path = path.with_name("events.jsonl")
        events_path.write_text(str(response["events"]), encoding="utf-8")
        events_path.chmod(0o600)
    if result is not None:
        result_path = path.with_name("result.json")
        result_path.write_bytes(canonical_json_bytes(result))
        result_path.chmod(0o600)
    return BenchmarkRun(manifest=manifest, result=result, manifest_path=path)


def validate_comparison_pair(h_manifest: RunManifest, j_manifest: RunManifest) -> None:
    controls = (
        "experiment",
        "edition",
        "model",
        "effort",
        "prompt_version",
        "prompt_digest",
        "system_instructions_digest",
        "profile_version",
        "profile_digest",
        "source_snapshot_digest",
        "randomization_seed",
        "tool_policy",
    )
    for field in controls:
        if getattr(h_manifest, field) != getattr(j_manifest, field):
            raise PairValidationError(f"comparison control differs: {field}")
    if {h_manifest.arm, j_manifest.arm} != {"H", "J"}:
        raise PairValidationError("comparison must contain one H and one J arm")


def run_experiment_a(
    *,
    capture: FrozenCapture,
    config: ExperimentConfig,
    executor_factory: Callable[[], Executor],
    artifact_dir: str | Path,
) -> ExperimentPair:
    order = ["H", "J"]
    random.Random(config.randomization_seed).shuffle(order)
    runs: dict[str, BenchmarkRun] = {}
    for arm in order:
        runs[arm] = run_arm(
            capture=capture,
            arm=arm,
            config=config,
            executor=executor_factory(),
            artifact_dir=artifact_dir,
        )
    validate_comparison_pair(runs["H"].manifest, runs["J"].manifest)
    return ExperimentPair(runs=runs)


def build_blind_packet(
    *, edition: str, outputs: Mapping[str, BenchmarkResult], seed: int
) -> BlindPacket:
    if set(outputs) != {"H", "J"}:
        raise ValueError("blind packet needs H and J outputs")
    origin_pattern = re.compile(
        r"\b(?:(?:the|this)\s+)?(?:supplied|provided|source|input)\s+"
        r"(?:html|json)(?:\s+(?:page|payload|source|input|representation))?\b"
        r"|\b(?:html|json)\s+(?:page|source|input|representation)\b"
        r"|\b(?:in|from|unlike)\s+(?:(?:the|this)\s+)?(?:html|json)\b"
        r"|\bappears?\s+to\s+be\s+(?:html|json)\b"
        r"|\b(?:the|this)\s+(?:html|json)\s+"
        r"(?:digest|response|page|payload|source|input|representation)\b",
        re.IGNORECASE,
    )
    for result in outputs.values():
        if origin_pattern.search(result.model_dump_json()):
            raise ValueError("blind packet contains origin-revealing model text")
    order = ["H", "J"]
    random.Random(seed).shuffle(order)
    packet = BlindPacket(
        edition=edition,
        responses=[
            BlindResponse(label=label, output=outputs[arm])
            for label, arm in zip(("A", "B"), order, strict=True)
        ],
    )
    packet._mapping = {label: arm for label, arm in zip(("A", "B"), order, strict=True)}
    return packet


def render_blind_review_markdown(packet: BlindPacket) -> str:
    """Render an origin-blind, human-first review sheet."""
    lines = [
        f"# x402 digest blind review — {packet.edition}",
        "",
        "Do not inspect the private unblinding key before completing this review.",
        "",
        "## Evaluation",
        "",
        "- Better identified what matters this week: A / B / tie",
        "- More useful next actions: A / B / tie",
        "- Material factual or evidence error in A: yes / no (note)",
        "- Material factual or evidence error in B: yes / no (note)",
        "- Overall preference: A / B / tie",
        "- Downstream reaction: follow / noise / reply / investigate / implement / other",
        "",
    ]
    for response in packet.responses:
        result = response.output
        lines.extend(
            (
                f"## Response {response.label}",
                "",
                f"**Weekly thesis:** {result.weekly_thesis}",
                "",
            )
        )
        for index, item in enumerate(result.top_items, start=1):
            lines.extend(
                (
                    f"### {index}. {item.id}",
                    "",
                    f"- Why it matters: {item.reason}",
                    f"- Next action: {item.recommended_action}",
                    "- Evidence:",
                )
            )
            lines.extend(f"  - {url}" for url in item.evidence_urls)
            lines.append("")
        lines.append("**Uncertainties:**")
        if result.uncertainties:
            lines.extend(f"- {item}" for item in result.uncertainties)
        else:
            lines.append("- None stated")
        lines.append("")
    return "\n".join(lines)


def run_vertical_slice(
    *,
    edition: str,
    source_loader: Callable[[], object],
    render_html: Callable[[object], str],
    render_json: Callable[[object], object],
    config: ExperimentConfig,
    executor_factory: Callable[[], Executor],
    artifact_dir: str | Path,
) -> VerticalSliceResult:
    root = Path(artifact_dir)
    capture = capture_edition(
        edition=edition,
        source_loader=source_loader,
        render_html=render_html,
        render_json=render_json,
        artifact_dir=root / "capture",
    )
    validate_formal_eligibility(capture)
    pair = run_experiment_a(
        capture=capture,
        config=config,
        executor_factory=executor_factory,
        artifact_dir=root / "runs",
    )
    outputs = {arm: run.result for arm, run in pair.runs.items()}
    if any(result is None for result in outputs.values()):
        raise RuntimeError("both arms must produce valid results before blinding")
    packet = build_blind_packet(
        edition=edition,
        outputs={arm: result for arm, result in outputs.items() if result is not None},
        seed=config.randomization_seed,
    )
    packet_path = root / "blind" / "review.json"
    packet_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    packet_path.write_bytes(canonical_json_bytes(packet))
    packet_path.chmod(0o600)
    review_path = packet_path.with_name("review.md")
    review_path.write_text(render_blind_review_markdown(packet), encoding="utf-8")
    review_path.chmod(0o600)
    key_path = root / "private" / "unblinding.json"
    key_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    key_path.write_bytes(canonical_json_bytes(packet._mapping))
    key_path.chmod(0o600)
    return VerticalSliceResult(
        capture=capture,
        runs=pair.runs,
        blind_packet=packet,
        blind_packet_path=packet_path,
    )
