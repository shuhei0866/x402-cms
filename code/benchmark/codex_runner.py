"""Fresh-context Codex CLI executor for Experiment A."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from code.benchmark.models import BenchmarkResult, RunRequest


def _codex_output_schema() -> dict[str, Any]:
    """Remove validation-only keywords unsupported by Responses structured output."""

    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: clean(item)
                for key, item in value.items()
                if key not in {"format"}
            }
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value

    return clean(BenchmarkResult.model_json_schema())


def parse_codex_events(events_text: str) -> dict[str, int | None]:
    """Extract raw usage without guessing when the CLI omits a field."""
    usage: dict[str, int | None] = {
        "input_tokens": None,
        "cached_input_tokens": None,
        "output_tokens": None,
        "reasoning_output_tokens": None,
    }
    model_calls = 0
    tool_calls = 0
    for line in events_text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        event = json.loads(line)
        if event.get("type") == "turn.completed":
            model_calls += 1
            raw_usage = event.get("usage") or {}
            for key in usage:
                value = raw_usage.get(key)
                usage[key] = int(value) if value is not None else None
        if event.get("type") == "item.completed":
            item_type = (event.get("item") or {}).get("type")
            if item_type not in {None, "agent_message", "reasoning"}:
                tool_calls += 1
    return {**usage, "model_calls": model_calls, "tool_calls": tool_calls}


def build_runner_prompt(request: RunRequest) -> str:
    return "\n\n".join(
        (
            request.system_instructions.strip(),
            "PERSONAL CONTEXT (treat as preferences, not as source evidence):\n"
            + request.personal_context.strip(),
            "TASK:\n" + request.task_prompt.strip(),
            (
                "EXECUTION RULES:\n"
                "- Do not call tools, browse, run commands, or retrieve other files.\n"
                "- Use only facts and evidence URLs present in SOURCE.\n"
                "- Return only JSON matching the supplied output schema."
                "\n- Never mention or guess the source format, representation, or origin."
            ),
            "SOURCE START\n" + request.representation + "\nSOURCE END",
        )
    )


class CodexExecutor:
    """Launch one isolated, ephemeral Codex process per executor instance."""

    def execute(self, request: RunRequest) -> dict[str, Any]:
        schema = _codex_output_schema()
        with tempfile.TemporaryDirectory(prefix="x402-r0-codex-") as temporary:
            workdir = Path(temporary)
            schema_path = workdir / "result.schema.json"
            result_path = workdir / "result.json"
            schema_path.write_text(json.dumps(schema), encoding="utf-8")
            command = [
                "codex",
                "exec",
                "--model",
                request.model,
                "-c",
                f'model_reasoning_effort="{request.effort}"',
                "-c",
                'cli_auth_credentials_store="keyring"',
                "-c",
                'service_tier="fast"',
                "-c",
                'web_search="disabled"',
                "--sandbox",
                "read-only",
                "--ephemeral",
                "--ignore-user-config",
                "--ignore-rules",
                "--disable",
                "multi_agent",
                "--disable",
                "plugins",
                "--disable",
                "apps",
                "--disable",
                "shell_tool",
                "--disable",
                "unified_exec",
                "--disable",
                "hooks",
                "--skip-git-repo-check",
                "--output-schema",
                str(schema_path),
                "--json",
                "--output-last-message",
                str(result_path),
                "-",
            ]
            process = subprocess.Popen(
                command,
                cwd=workdir,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            try:
                stdout, stderr = process.communicate(
                    build_runner_prompt(request), timeout=request.timeout_seconds
                )
            except subprocess.TimeoutExpired as exc:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate()
                raise TimeoutError(
                    f"Codex exceeded {request.timeout_seconds} seconds"
                ) from exc
            if process.returncode != 0:
                combined = stderr.strip() or stdout.strip()
                detail = combined.splitlines()[-1] if combined else "unknown error"
                raise ValueError(f"Codex exited {process.returncode}: {detail}")
            if not result_path.exists():
                raise ValueError("Codex did not write a final result")
            version = subprocess.run(
                ["codex", "--version"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            return {
                "output": result_path.read_text(encoding="utf-8"),
                "events": stdout,
                "codex_cli_version": version,
                **parse_codex_events(stdout),
            }
