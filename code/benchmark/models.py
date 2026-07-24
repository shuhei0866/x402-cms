"""Typed contracts for the R0 agent-friendliness benchmark."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    model_validator,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BenchmarkItem(_StrictModel):
    id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    evidence_urls: list[AnyHttpUrl] = Field(min_length=1)
    recommended_action: str = Field(min_length=1)


class BenchmarkResult(_StrictModel):
    weekly_thesis: str = Field(min_length=1)
    top_items: list[BenchmarkItem] = Field(min_length=3, max_length=3)
    uncertainties: list[str]


class ResultChecks(_StrictModel):
    response_schema_valid: bool = True
    exactly_three_items_valid: bool = True
    evidence_urls_present: bool
    duplicate_recommendation_count: int = Field(ge=0)


class RunMetrics(_StrictModel):
    input_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    reasoning_output_tokens: int | None = Field(default=None, ge=0)
    input_bytes: int = Field(ge=0)
    representation_bytes: int | None = Field(default=None, ge=0)
    wall_clock_ms: int = Field(ge=0)
    model_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    response_schema_valid: bool
    exactly_three_items_valid: bool
    evidence_urls_present: bool
    duplicate_recommendation_count: int = Field(ge=0)


class RunManifest(_StrictModel):
    schema_version: Literal["r0-run-manifest-v1"]
    run_id: str = Field(min_length=1)
    experiment: Literal["A"]
    status: Literal["completed", "failed", "timeout"]
    edition: str
    arm: Literal["H", "J"]
    model: str = Field(min_length=1)
    effort: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    prompt_digest: str
    system_instructions_digest: str
    profile_version: str = Field(min_length=1)
    profile_digest: str
    source_snapshot_digest: str
    representation_digest: str | None = None
    runner_input_digest: str | None = None
    codex_cli_version: str | None = None
    randomization_seed: int
    started_at: datetime
    completed_at: datetime
    tool_policy: str = Field(min_length=1)
    failure_reason: str | None = None
    metrics: RunMetrics

    @model_validator(mode="after")
    def _validate_time_order(self) -> RunManifest:
        if self.started_at.tzinfo is None or self.completed_at.tzinfo is None:
            raise ValueError("run timestamps must be timezone-aware")
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must not precede started_at")
        return self


class ExperimentConfig(_StrictModel):
    model: str = Field(min_length=1)
    effort: str = Field(min_length=1)
    system_instructions: str = Field(min_length=1, exclude=True, repr=False)
    task_prompt: str = Field(min_length=1, exclude=True, repr=False)
    prompt_version: str = Field(min_length=1)
    personal_context: str = Field(min_length=1, exclude=True, repr=False)
    profile_version: str = Field(min_length=1)
    tool_policy: str = Field(min_length=1)
    randomization_seed: int


class CaptureArm(_StrictModel):
    arm: Literal["H", "J"]
    media_type: str
    source_snapshot_digest: str
    body_digest: str
    body_bytes: int = Field(ge=1)


@dataclass(frozen=True)
class FrozenCapture:
    edition: str
    source_snapshot_digest: str
    snapshot: object
    arms: dict[str, CaptureArm]
    representations: dict[str, str]
    manifest_path: Path


@dataclass(frozen=True)
class RunRequest:
    arm: Literal["H", "J"]
    model: str
    effort: str
    system_instructions: str
    task_prompt: str
    personal_context: str
    representation: str
    tool_policy: str
    fresh_context: bool = True
    timeout_seconds: int = 90


@dataclass(frozen=True)
class BenchmarkRun:
    manifest: RunManifest
    result: BenchmarkResult | None
    manifest_path: Path


@dataclass(frozen=True)
class ExperimentPair:
    runs: dict[str, BenchmarkRun]


class BlindResponse(_StrictModel):
    label: Literal["A", "B"]
    output: BenchmarkResult


class BlindPacket(_StrictModel):
    schema_version: Literal["r0-blind-packet-v1"] = "r0-blind-packet-v1"
    edition: str
    responses: list[BlindResponse] = Field(min_length=2, max_length=2)

    _mapping: dict[str, str] = PrivateAttr(default_factory=dict)


@dataclass(frozen=True)
class VerticalSliceResult:
    capture: FrozenCapture
    runs: dict[str, BenchmarkRun]
    blind_packet: BlindPacket
    blind_packet_path: Path
