"""Content-addressed, write-once capture for Experiment A."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from code.benchmark.models import CaptureArm, FrozenCapture

class CaptureError(RuntimeError):
    """The edition could not be frozen without violating the capture contract."""


def validate_artifact_dir(path: str | Path) -> Path:
    """Allow only OS temp paths or paths ignored by their containing git repo."""
    target = Path(path).resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    try:
        target.relative_to(temp_root)
        return target
    except ValueError:
        pass

    existing = target
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    repository = subprocess.run(
        ["git", "-C", str(existing), "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
    )
    if repository.returncode == 0:
        ignored = subprocess.run(
            ["git", "-C", repository.stdout.strip(), "check-ignore", "--no-index", "-q", str(target)],
            check=False,
        )
        if ignored.returncode == 0:
            return target
        raise CaptureError("raw benchmark artifact path is tracked or not ignored")
    raise CaptureError("raw benchmark artifacts require an ignored git path or OS temp")


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def wire_json_bytes(value: Any) -> bytes:
    """Encode like Starlette JSONResponse while preserving renderer key order."""
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_digest(data: bytes | str) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _write_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.tmp")
    with open(temporary, "xb") as handle:
        handle.write(data)
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def capture_edition(
    *,
    edition: str,
    source_loader: Callable[[], object],
    render_html: Callable[[object], str],
    render_json: Callable[[object], object],
    artifact_dir: str | Path,
) -> FrozenCapture:
    """Load once, freeze canonically, and render two independent thawed copies."""
    target = validate_artifact_dir(artifact_dir)
    manifest_path = target / "capture-manifest.json"
    if manifest_path.exists():
        raise CaptureError(f"edition is already frozen at {manifest_path}")

    source_bytes = canonical_json_bytes(source_loader())
    snapshot = json.loads(source_bytes)
    if isinstance(snapshot, dict) and snapshot.get("week") not in {None, edition}:
        raise CaptureError("capture edition does not match frozen snapshot week")
    snapshot_digest = sha256_digest(source_bytes)

    html_body = render_html(copy.deepcopy(snapshot))
    json_value = render_json(copy.deepcopy(snapshot))
    json_bytes = wire_json_bytes(json_value)
    if not isinstance(html_body, str) or not html_body.strip():
        raise CaptureError("HTML arm is empty")
    if json_value in ({}, [], None, "") or not json_bytes.strip():
        raise CaptureError("JSON arm is empty")

    html_bytes = html_body.encode("utf-8")
    json_body = json_bytes.decode("utf-8")
    arms = {
        "H": CaptureArm(
            arm="H",
            media_type="text/html",
            source_snapshot_digest=snapshot_digest,
            body_digest=sha256_digest(html_bytes),
            body_bytes=len(html_bytes),
        ),
        "J": CaptureArm(
            arm="J",
            media_type="application/json",
            source_snapshot_digest=snapshot_digest,
            body_digest=sha256_digest(json_bytes),
            body_bytes=len(json_bytes),
        ),
    }
    manifest = {
        "schema_version": "r0-capture-v1",
        "edition": edition,
        "source_snapshot_digest": snapshot_digest,
        "arms": {key: arm.model_dump(mode="json") for key, arm in arms.items()},
    }

    # Nothing is written until both representations have passed validation.
    _write_private(target / "snapshot.json", source_bytes)
    _write_private(target / "representations" / "H.html", html_bytes)
    _write_private(target / "representations" / "J.json", json_bytes)
    _write_private(manifest_path, canonical_json_bytes(manifest))
    return FrozenCapture(
        edition=edition,
        source_snapshot_digest=snapshot_digest,
        snapshot=snapshot,
        arms=arms,
        representations={"H": html_body, "J": json_body},
        manifest_path=manifest_path,
    )


def load_frozen_capture(artifact_dir: str | Path) -> FrozenCapture:
    """Load and verify a previously frozen capture without re-reading its source."""
    target = Path(artifact_dir)
    manifest_path = target / "capture-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    snapshot_bytes = (target / "snapshot.json").read_bytes()
    snapshot_digest = sha256_digest(snapshot_bytes)
    if snapshot_digest != manifest["source_snapshot_digest"]:
        raise CaptureError("snapshot digest does not match capture manifest")
    snapshot = json.loads(snapshot_bytes)
    if isinstance(snapshot, dict) and snapshot.get("week") not in {
        None,
        manifest["edition"],
    }:
        raise CaptureError("capture edition does not match frozen snapshot week")
    representations = {
        "H": (target / "representations" / "H.html").read_text(encoding="utf-8"),
        "J": (target / "representations" / "J.json").read_text(encoding="utf-8"),
    }
    arms = {
        key: CaptureArm.model_validate(value)
        for key, value in manifest["arms"].items()
    }
    for key, body in representations.items():
        if sha256_digest(body) != arms[key].body_digest:
            raise CaptureError(f"{key} representation digest does not match manifest")
    return FrozenCapture(
        edition=manifest["edition"],
        source_snapshot_digest=snapshot_digest,
        snapshot=snapshot,
        arms=arms,
        representations=representations,
        manifest_path=manifest_path,
    )
