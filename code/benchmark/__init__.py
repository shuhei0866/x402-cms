"""Public facade for the R0 agent-friendliness benchmark."""

from code.benchmark.capture import CaptureError, capture_edition, load_frozen_capture
from code.benchmark.harness import (
    IneligibleEditionError,
    PairValidationError,
    build_blind_packet,
    evaluate_result,
    render_blind_review_markdown,
    run_arm,
    run_experiment_a,
    run_vertical_slice,
    validate_comparison_pair,
    validate_formal_eligibility,
)
from code.benchmark.models import BenchmarkResult, ExperimentConfig, RunManifest

__all__ = [
    "BenchmarkResult",
    "CaptureError",
    "ExperimentConfig",
    "IneligibleEditionError",
    "PairValidationError",
    "RunManifest",
    "build_blind_packet",
    "capture_edition",
    "evaluate_result",
    "render_blind_review_markdown",
    "run_arm",
    "run_experiment_a",
    "run_vertical_slice",
    "load_frozen_capture",
    "validate_comparison_pair",
    "validate_formal_eligibility",
]
