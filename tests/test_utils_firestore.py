"""Tests for the shared Firestore client builder.

Every reader, writer, publisher, and orchestrator went through the
same three-branch construction pattern (inject > project > ADC).
Centralising it kills four copies and pins the precedence in one
place that the rest of the code points at.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from code.utils.firestore import build_client


class TestBuildClient:
    def test_returns_injected_client_unchanged(self) -> None:
        injected = MagicMock()
        assert build_client(injected) is injected

    def test_builds_with_project_when_no_client(self) -> None:
        with patch("code.utils.firestore.firestore.Client") as Ctor:
            sentinel = MagicMock()
            Ctor.return_value = sentinel
            result = build_client(client=None, project="my-utilities-490202")
            assert result is sentinel
            Ctor.assert_called_once_with(project="my-utilities-490202")

    def test_builds_with_adc_when_no_args(self) -> None:
        with patch("code.utils.firestore.firestore.Client") as Ctor:
            sentinel = MagicMock()
            Ctor.return_value = sentinel
            result = build_client()
            assert result is sentinel
            Ctor.assert_called_once_with()

    def test_injected_client_wins_over_project(self) -> None:
        # Precedence sanity: an explicit injection short-circuits the
        # project branch — tests rely on this to drive readers without
        # ever touching the real Firestore SDK.
        injected = MagicMock()
        with patch("code.utils.firestore.firestore.Client") as Ctor:
            assert build_client(injected, project="ignored") is injected
            Ctor.assert_not_called()
