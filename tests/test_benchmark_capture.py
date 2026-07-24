"""Red tests for freezing one source snapshot into the H and J arms."""

from __future__ import annotations

from pathlib import Path

import pytest

from code.benchmark import CaptureError, capture_edition
from code.benchmark.capture import validate_artifact_dir

REPO_ROOT = Path(__file__).resolve().parents[1]


def _source() -> dict:
    return {
        "week": "2026-W27",
        "items": [
            {
                "id": "github:x402-foundation/x402#2701",
                "title": "Make settlement errors actionable",
                "url": "https://github.com/x402-foundation/x402/pull/2701",
            }
        ],
    }


def _capture(tmp_path: Path):
    return capture_edition(
        edition="2026-W27",
        source_loader=_source,
        render_html=lambda source: (
            '<html><a href="'
            + source["items"][0]["url"]
            + '">Make settlement errors actionable</a></html>'
        ),
        render_json=lambda source: {
            "week": source["week"],
            "items": source["items"],
        },
        artifact_dir=tmp_path,
    )


def test_capture_loads_source_once_and_renders_both_arms_from_one_snapshot(
    tmp_path: Path,
) -> None:
    loader_calls = 0
    renderer_inputs: list[dict] = []

    def load_source() -> dict:
        nonlocal loader_calls
        loader_calls += 1
        return _source()

    def render_html(source: dict) -> str:
        renderer_inputs.append(source)
        return "<html>W27 source</html>"

    def render_json(source: dict) -> dict:
        renderer_inputs.append(source)
        return {"week": source["week"], "items": source["items"]}

    capture = capture_edition(
        edition="2026-W27",
        source_loader=load_source,
        render_html=render_html,
        render_json=render_json,
        artifact_dir=tmp_path,
    )

    assert loader_calls == 1
    assert renderer_inputs == [_source(), _source()]
    assert capture.edition == "2026-W27"
    assert capture.arms["H"].source_snapshot_digest == capture.source_snapshot_digest
    assert capture.arms["J"].source_snapshot_digest == capture.source_snapshot_digest
    assert capture.arms["H"].body_digest != capture.arms["J"].body_digest
    assert capture.manifest_path.is_file()


def test_capture_rejects_empty_arm_before_freezing(tmp_path: Path) -> None:
    cases = (
        (lambda source: "", lambda source: {"week": source["week"]}),
        (lambda source: "<html>non-empty</html>", lambda source: {}),
    )

    for index, (render_html, render_json) in enumerate(cases):
        target = tmp_path / str(index)
        target.mkdir()

        with pytest.raises(CaptureError, match="empty"):
            capture_edition(
                edition="2026-W27",
                source_loader=_source,
                render_html=render_html,
                render_json=render_json,
                artifact_dir=target,
            )

        assert list(target.iterdir()) == []


def test_frozen_capture_is_write_once(tmp_path: Path) -> None:
    original = _capture(tmp_path)
    original_manifest = original.manifest_path.read_bytes()

    with pytest.raises(CaptureError, match="already|frozen|exists"):
        _capture(tmp_path)

    assert original.manifest_path.read_bytes() == original_manifest
    assert original.source_snapshot_digest


def test_json_representation_preserves_renderer_key_order(tmp_path: Path) -> None:
    capture = _capture(tmp_path)

    assert capture.representations["J"].startswith('{"week":"2026-W27","items":')


def test_capture_rejects_edition_snapshot_week_mismatch(tmp_path: Path) -> None:
    with pytest.raises(CaptureError, match="week|edition"):
        capture_edition(
            edition="2026-W27",
            source_loader=lambda: {**_source(), "week": "2026-W28"},
            render_html=lambda source: "<html>content</html>",
            render_json=lambda source: source,
            artifact_dir=tmp_path,
        )


def test_capture_refuses_raw_artifacts_in_tracked_repo_path() -> None:
    with pytest.raises(CaptureError, match="benchmark_artifacts|tracked"):
        capture_edition(
            edition="2026-W27",
            source_loader=_source,
            render_html=lambda source: "<html>content</html>",
            render_json=lambda source: source,
            artifact_dir=REPO_ROOT / "benchmarks" / "agent_friendliness" / "leak-test",
        )


def test_artifact_guard_refuses_tracked_path_in_another_repo() -> None:
    other_clone = Path("/Users/snufkin/Documents/programing/x402-cms")
    if not other_clone.is_dir():
        pytest.skip("other x402-cms clone is not present")

    with pytest.raises(CaptureError, match="ignored|artifact"):
        validate_artifact_dir(other_clone / "benchmarks" / "leak-test")
