"""Tests for the X indexer orchestrator.

`load_tracked_handles` reads a YAML list of handles. `run_for_week`
glues the network and storage steps together for one ISO week. The
tests inject every external dependency — handles list, httpx client,
Firestore client — so the orchestrator itself stays under unit-test
discipline and never touches the real X API.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from code.indexers.x_indexer import load_tracked_handles, run_for_week


def _tweet_row(post_id: str, created_at: str) -> dict:
    return {
        "id": post_id,
        "text": f"tweet {post_id}",
        "created_at": created_at,
        "conversation_id": post_id,
    }


class TestLoadTrackedHandles:
    def test_reads_flat_yaml_list(self, tmp_path: Path) -> None:
        path = tmp_path / "tracked_handles.yaml"
        path.write_text("- phdargen\n- CarsonRoscoe\n- ethanoroshiba\n")
        assert load_tracked_handles(path) == [
            "phdargen",
            "CarsonRoscoe",
            "ethanoroshiba",
        ]

    def test_strips_leading_at_signs(self, tmp_path: Path) -> None:
        path = tmp_path / "tracked_handles.yaml"
        path.write_text("- '@phdargen'\n- CarsonRoscoe\n")
        assert load_tracked_handles(path) == ["phdargen", "CarsonRoscoe"]

    def test_skips_blank_and_comment_only_entries(self, tmp_path: Path) -> None:
        path = tmp_path / "tracked_handles.yaml"
        path.write_text("- phdargen\n- ''\n- '   '\n")
        assert load_tracked_handles(path) == ["phdargen"]

    def test_missing_file_raises_filenotfound(self, tmp_path: Path) -> None:
        path = tmp_path / "nope.yaml"
        with pytest.raises(FileNotFoundError):
            load_tracked_handles(path)


class TestRunForWeek:
    def test_resolves_each_handle_then_writes_collected_posts(self) -> None:
        # Handler scripts two phases:
        # 1. resolve `/2/users/by/username/{handle}` -> returns numeric id
        # 2. fetch `/2/users/{id}/tweets` -> returns 1 tweet per user
        handle_to_id = {"phdargen": "111", "CarsonRoscoe": "222"}

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if "/2/users/by/username/" in path:
                handle = path.rsplit("/", 1)[-1]
                return httpx.Response(
                    200,
                    json={"data": {"id": handle_to_id[handle], "username": handle}},
                )
            assert "/2/users/" in path and path.endswith("/tweets")
            user_id = path.split("/2/users/")[1].split("/tweets")[0]
            return httpx.Response(
                200,
                json={
                    "data": [_tweet_row(f"p{user_id}", "2026-05-05T12:00:00.000Z")],
                    "meta": {"result_count": 1},
                },
            )

        fs_client = MagicMock()
        client = httpx.Client(transport=httpx.MockTransport(handler))

        result = run_for_week(
            week="2026-W19",
            handles=["phdargen", "CarsonRoscoe"],
            bearer="test-bearer",
            client=client,
            fs_client=fs_client,
        )

        assert result["week"] == "2026-W19"
        assert result["handles_processed"] == 2
        assert result["handles_failed"] == 0
        assert result["posts_fetched"] == 2
        assert result["posts_written"] == 2

        # The writer was called once with both posts.
        collection = fs_client.collection.return_value
        document_ids = [
            call.args[0] for call in collection.document.call_args_list
        ]
        assert sorted(document_ids) == ["p111", "p222"]

        client.close()

    def test_dry_run_skips_writes_and_returns_posts(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if "/by/username/" in request.url.path:
                return httpx.Response(200, json={"data": {"id": "1"}})
            return httpx.Response(
                200,
                json={
                    "data": [_tweet_row("100", "2026-05-05T12:00:00.000Z")],
                    "meta": {"result_count": 1},
                },
            )

        fs_client = MagicMock()
        client = httpx.Client(transport=httpx.MockTransport(handler))

        result = run_for_week(
            week="2026-W19",
            handles=["phdargen"],
            bearer="t",
            client=client,
            fs_client=fs_client,
            dry_run=True,
        )

        assert result["posts_fetched"] == 1
        assert result["posts_written"] == 0
        # Firestore must not be touched in dry-run mode.
        fs_client.collection.assert_not_called()

        client.close()

    def test_handle_not_found_is_recorded_and_run_continues(self) -> None:
        # Mixed roster: one good handle, one 404. The run should
        # report the failure but still write the good handle's tweets.
        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path.endswith("/by/username/missing"):
                return httpx.Response(
                    404,
                    json={"errors": [{"detail": "not found"}]},
                )
            if "/by/username/" in path:
                return httpx.Response(200, json={"data": {"id": "111"}})
            return httpx.Response(
                200,
                json={
                    "data": [_tweet_row("p1", "2026-05-05T12:00:00.000Z")],
                    "meta": {"result_count": 1},
                },
            )

        fs_client = MagicMock()
        client = httpx.Client(transport=httpx.MockTransport(handler))

        result = run_for_week(
            week="2026-W19",
            handles=["phdargen", "missing"],
            bearer="t",
            client=client,
            fs_client=fs_client,
        )

        assert result["handles_processed"] == 1
        assert result["handles_failed"] == 1
        assert "missing" in result["failed_handles"]
        assert result["posts_written"] == 1

        client.close()
