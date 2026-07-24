"""Red contract tests for the complete R0-A W27 vertical slice."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from code.benchmark import (
    BenchmarkResult,
    ExperimentConfig,
    IneligibleEditionError,
    PairValidationError,
    RunManifest,
    build_blind_packet,
    capture_edition,
    evaluate_result,
    run_arm,
    run_experiment_a,
    run_vertical_slice,
    validate_comparison_pair,
    validate_formal_eligibility,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
URLS = (
    "https://github.com/x402-foundation/x402/pull/2701",
    "https://github.com/x402-foundation/x402/issues/2702",
    "https://x.com/x402/status/123",
)


def _result_data(*, duplicate_ids: bool = False) -> dict:
    ids = ["pr:2701", "issue:2702", "x:123"]
    if duplicate_ids:
        ids[1] = ids[0]
    return {
        "weekly_thesis": "Operational reliability became the week's main theme.",
        "top_items": [
            {
                "id": item_id,
                "reason": f"Reason {index}",
                "evidence_urls": [URLS[index]],
                "recommended_action": f"Investigate item {index}",
            }
            for index, item_id in enumerate(ids)
        ],
        "uncertainties": [],
    }


def _source() -> dict:
    return {
        "week": "2026-W27",
        "items": [
            {"id": f"item:{index}", "url": url, "title": f"Item {index}"}
            for index, url in enumerate(URLS)
        ],
    }


def _capture(tmp_path: Path, *, edition: str = "2026-W27"):
    source = _source()
    source["week"] = edition
    return capture_edition(
        edition=edition,
        source_loader=lambda: source,
        render_html=lambda source: "<html>" + " ".join(URLS) + "</html>",
        render_json=lambda source: source,
        artifact_dir=tmp_path,
    )


def _config(*, private_context: str = "batch settlement; Japanese contributors"):
    return ExperimentConfig(
        model="gpt-5.3-codex",
        effort="high",
        system_instructions="Use only the supplied representation. Return JSON.",
        task_prompt="Select three important x402 items and recommend actions.",
        prompt_version="r0-task-v1",
        personal_context=private_context,
        profile_version="shuhei-x402-v1",
        tool_policy="no-retrieval",
        randomization_seed=27,
    )


def _manifest_data() -> dict:
    return {
        "schema_version": "r0-run-manifest-v1",
        "run_id": "2026-W27-H-001",
        "experiment": "A",
        "status": "completed",
        "edition": "2026-W27",
        "arm": "H",
        "model": "gpt-5.3-codex",
        "effort": "high",
        "prompt_version": "r0-task-v1",
        "prompt_digest": "sha256:" + "1" * 64,
        "system_instructions_digest": "sha256:" + "2" * 64,
        "profile_version": "shuhei-x402-v1",
        "profile_digest": "sha256:" + "3" * 64,
        "source_snapshot_digest": "sha256:" + "4" * 64,
        "randomization_seed": 27,
        "started_at": "2026-07-13T03:00:00Z",
        "completed_at": "2026-07-13T03:00:42Z",
        "tool_policy": "no-retrieval",
        "metrics": {
            "input_tokens": 1200,
            "output_tokens": 320,
            "input_bytes": 8400,
            "wall_clock_ms": 42000,
            "model_calls": 1,
            "tool_calls": 0,
            "response_schema_valid": True,
            "exactly_three_items_valid": True,
            "evidence_urls_present": True,
            "duplicate_recommendation_count": 0,
        },
    }


class FakeExecutor:
    def __init__(self, output: str | None = None) -> None:
        self.output = output or json.dumps(_result_data())
        self.requests: list[object] = []

    def execute(self, request) -> dict:
        self.requests.append(request)
        return {
            "output": self.output,
            "input_tokens": 1200,
            "output_tokens": 320,
            "model_calls": 1,
            "tool_calls": 0,
        }


class ToolCallingExecutor(FakeExecutor):
    def execute(self, request) -> dict:
        response = super().execute(request)
        response["tool_calls"] = 1
        return response


class CrashingExecutor:
    def execute(self, request) -> dict:
        raise RuntimeError("executor crashed")


class TestResultContract:
    def test_valid_result_requires_exactly_three_complete_items(self) -> None:
        result = BenchmarkResult.model_validate(_result_data())
        assert len(result.top_items) == 3
        assert result.model_dump(mode="json") == _result_data()

    def test_result_rejects_non_three_item_counts(self) -> None:
        for count in (0, 1, 2, 4):
            payload = _result_data()
            payload["top_items"] = payload["top_items"][:count]
            if count == 4:
                payload["top_items"].append(
                    {
                        "id": "pr:fourth",
                        "reason": "Extra item",
                        "evidence_urls": [URLS[0]],
                        "recommended_action": "Do another thing",
                    }
                )
            with pytest.raises(ValidationError):
                BenchmarkResult.model_validate(payload)

    def test_evidence_presence_is_measured_against_current_arm_only(self) -> None:
        result = BenchmarkResult.model_validate(_result_data())
        matching = evaluate_result(result, representation=" ".join(URLS))
        other_arm = evaluate_result(
            result,
            representation="https://example.com/a-url-from-only-the-other-arm",
        )
        assert matching.evidence_urls_present is True
        assert other_arm.evidence_urls_present is False

    def test_duplicate_item_ids_are_counted(self) -> None:
        result = BenchmarkResult.model_validate(_result_data(duplicate_ids=True))
        checks = evaluate_result(result, representation=" ".join(URLS))
        assert checks.duplicate_recommendation_count == 1

    def test_html_escaped_evidence_url_is_still_present(self) -> None:
        payload = _result_data()
        payload["top_items"][0]["evidence_urls"] = [
            "https://example.com/source?a=1&b=2"
        ]
        result = BenchmarkResult.model_validate(payload)

        checks = evaluate_result(
            result,
            representation='<a href="https://example.com/source?a=1&amp;b=2">source</a> '
            + " ".join(URLS[1:]),
        )

        assert checks.evidence_urls_present is True


class TestManifestAndEligibility:
    def test_completed_w27_manifest_contains_required_provenance_and_metrics(
        self,
    ) -> None:
        manifest = RunManifest.model_validate(_manifest_data())
        assert manifest.edition == "2026-W27"
        assert manifest.metrics.input_tokens == 1200
        assert manifest.metrics.wall_clock_ms == 42000
        assert manifest.tool_policy == "no-retrieval"

    def test_manifest_rejects_private_profile_body(self) -> None:
        payload = _manifest_data()
        payload["profile_body"] = "DO-NOT-SERIALIZE-THIS-PRIVATE-PROFILE"
        with pytest.raises(ValidationError):
            RunManifest.model_validate(payload)

    def test_w28_cannot_enter_formal_scoring(self, tmp_path: Path) -> None:
        capture = _capture(tmp_path, edition="2026-W28")
        with pytest.raises(IneligibleEditionError, match="2026-W28|contaminated"):
            validate_formal_eligibility(capture)

    def test_w27_is_formally_eligible_when_capture_is_complete(
        self, tmp_path: Path
    ) -> None:
        capture = _capture(tmp_path)
        validate_formal_eligibility(capture)


class TestRunnerControls:
    def test_malformed_output_still_emits_failure_manifest(self, tmp_path: Path) -> None:
        capture = _capture(tmp_path / "capture")
        run = run_arm(
            capture=capture,
            arm="H",
            config=_config(),
            executor=FakeExecutor("not JSON"),
            artifact_dir=tmp_path / "runs",
        )
        assert run.result is None
        assert run.manifest.status == "failed"
        assert run.manifest.metrics.response_schema_valid is False
        assert run.manifest_path.is_file()

    def test_each_arm_uses_a_fresh_executor_context(self, tmp_path: Path) -> None:
        capture = _capture(tmp_path / "capture")
        executors: list[FakeExecutor] = []

        def executor_factory() -> FakeExecutor:
            executor = FakeExecutor()
            executors.append(executor)
            return executor

        pair = run_experiment_a(
            capture=capture,
            config=_config(),
            executor_factory=executor_factory,
            artifact_dir=tmp_path / "runs",
        )

        assert set(pair.runs) == {"H", "J"}
        assert len(executors) == 2
        assert all(len(executor.requests) == 1 for executor in executors)
        requests = [executor.requests[0] for executor in executors]
        assert all(request.fresh_context is True for request in requests)
        assert all(request.tool_policy == "no-retrieval" for request in requests)
        assert {request.arm for request in requests} == {"H", "J"}

    def test_tool_policy_violation_fails_the_run(self, tmp_path: Path) -> None:
        capture = _capture(tmp_path / "capture")
        run = run_arm(
            capture=capture,
            arm="H",
            config=_config(),
            executor=ToolCallingExecutor(),
            artifact_dir=tmp_path / "runs",
        )

        assert run.manifest.status == "failed"
        assert run.manifest.metrics.tool_calls == 1
        assert run.result is None

    def test_unexpected_executor_failure_still_emits_manifest(
        self, tmp_path: Path
    ) -> None:
        capture = _capture(tmp_path / "capture")
        run = run_arm(
            capture=capture,
            arm="H",
            config=_config(),
            executor=CrashingExecutor(),
            artifact_dir=tmp_path / "runs",
        )

        assert run.manifest.status == "failed"
        assert "executor crashed" in (run.manifest.failure_reason or "")
        assert run.manifest_path.is_file()

    def test_invalid_artifact_path_is_rejected_before_executor_runs(
        self, tmp_path: Path
    ) -> None:
        capture = _capture(tmp_path / "capture")
        executor = FakeExecutor()

        with pytest.raises(Exception, match="benchmark_artifacts|ignored|tracked"):
            run_arm(
                capture=capture,
                arm="H",
                config=_config(),
                executor=executor,
                artifact_dir=REPO_ROOT / "benchmarks" / "leak-test",
            )

        assert executor.requests == []

    def test_pair_validation_rejects_control_configuration_drift(self) -> None:
        h_manifest = RunManifest.model_validate(_manifest_data())
        j_data = _manifest_data()
        j_data.update({"run_id": "2026-W27-J-001", "arm": "J", "effort": "medium"})
        j_manifest = RunManifest.model_validate(j_data)

        with pytest.raises(PairValidationError, match="effort"):
            validate_comparison_pair(h_manifest, j_manifest)

    def test_run_manifest_does_not_leak_personal_context(self, tmp_path: Path) -> None:
        sentinel = "DO-NOT-SERIALIZE-THIS-PRIVATE-PROFILE"
        capture = _capture(tmp_path / "capture")
        run = run_arm(
            capture=capture,
            arm="H",
            config=_config(private_context=sentinel),
            executor=FakeExecutor(),
            artifact_dir=tmp_path / "runs",
        )
        manifest_json = run.manifest.model_dump_json()
        assert sentinel not in manifest_json
        assert "personal_context" not in manifest_json
        assert run.manifest.profile_digest


class TestBlindPacket:
    def test_packet_uses_neutral_labels_and_hides_origin(self) -> None:
        h = BenchmarkResult.model_validate(_result_data())
        j_data = _result_data()
        j_data["weekly_thesis"] = "JSON thesis"
        j = BenchmarkResult.model_validate(j_data)

        packet = build_blind_packet(
            edition="2026-W27", outputs={"H": h, "J": j}, seed=27
        )

        assert {response.label for response in packet.responses} == {"A", "B"}
        assert {response.output.weekly_thesis for response in packet.responses} == {
            h.weekly_thesis,
            j.weekly_thesis,
        }
        forbidden = {"arm", "origin", "representation", "input_path", "seed"}

        def all_keys(value) -> set[str]:
            if isinstance(value, dict):
                return set(value).union(*(all_keys(item) for item in value.values()))
            if isinstance(value, list):
                return set().union(*(all_keys(item) for item in value))
            return set()

        assert forbidden.isdisjoint(all_keys(packet.model_dump(mode="json")))

    def test_packet_order_is_reproducible_for_same_seed(self) -> None:
        outputs = {
            "H": BenchmarkResult.model_validate(_result_data()),
            "J": BenchmarkResult.model_validate(
                {**_result_data(), "weekly_thesis": "JSON thesis"}
            ),
        }
        first = build_blind_packet(edition="2026-W27", outputs=outputs, seed=27)
        second = build_blind_packet(edition="2026-W27", outputs=outputs, seed=27)
        assert first.model_dump(mode="json") == second.model_dump(mode="json")

    @pytest.mark.parametrize(
        "disclosure",
        (
            "The supplied HTML page emphasizes reliability.",
            "I found this in JSON.",
            "The response appears to be JSON.",
            "Unlike the HTML, the source is concise.",
            "The JSON digest emphasizes reliability.",
        ),
    )
    def test_packet_rejects_origin_revealing_model_text(self, disclosure: str) -> None:
        revealing = _result_data()
        revealing["weekly_thesis"] = disclosure
        outputs = {
            "H": BenchmarkResult.model_validate(revealing),
            "J": BenchmarkResult.model_validate(_result_data()),
        }

        with pytest.raises(ValueError, match="origin|blind"):
            build_blind_packet(edition="2026-W27", outputs=outputs, seed=27)


class TestArtifactPolicy:
    def test_raw_benchmark_artifacts_are_gitignored(self) -> None:
        paths = (
            "benchmark_artifacts/2026-W27/capture.html",
            "benchmark_artifacts/2026-W27/capture.json",
            "benchmark_artifacts/2026-W27/transcript.jsonl",
            "benchmark_artifacts/2026-W27/unblinding.json",
            "benchmarks/agent_friendliness/private/profile.json",
        )
        for path in paths:
            result = subprocess.run(
                ["git", "check-ignore", "--no-index", "-q", path],
                cwd=REPO_ROOT,
                check=False,
            )
            assert result.returncode == 0, f"expected ignored benchmark artifact: {path}"

    def test_public_benchmark_contracts_are_not_gitignored(self) -> None:
        paths = (
            "benchmarks/agent_friendliness/prompts/task-v1.md",
            "benchmarks/agent_friendliness/schemas/result-v1.json",
            "benchmarks/agent_friendliness/profiles/example.json",
            "benchmarks/agent_friendliness/reports/baseline.json",
        )
        for path in paths:
            result = subprocess.run(
                ["git", "check-ignore", "--no-index", "-q", path],
                cwd=REPO_ROOT,
                check=False,
            )
            assert result.returncode == 1, f"expected tracked benchmark contract: {path}"


def test_w27_vertical_slice_produces_capture_runs_and_blind_packet(
    tmp_path: Path,
) -> None:
    executors: list[FakeExecutor] = []
    loader_calls = 0

    def source_loader() -> dict:
        nonlocal loader_calls
        loader_calls += 1
        return _source()

    def executor_factory() -> FakeExecutor:
        executor = FakeExecutor()
        executors.append(executor)
        return executor

    result = run_vertical_slice(
        edition="2026-W27",
        source_loader=source_loader,
        render_html=lambda source: "<html>" + " ".join(URLS) + "</html>",
        render_json=lambda source: source,
        config=_config(),
        executor_factory=executor_factory,
        artifact_dir=tmp_path,
    )

    assert loader_calls == 1
    assert result.capture.source_snapshot_digest
    assert set(result.runs) == {"H", "J"}
    assert all(run.manifest.status == "completed" for run in result.runs.values())
    assert len(result.blind_packet.responses) == 2
    assert result.blind_packet_path.is_file()
