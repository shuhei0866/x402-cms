"""Smoke test that pytest discovery works and `code.*` imports resolve."""

from __future__ import annotations


def test_pytest_runs() -> None:
    assert True


def test_code_package_importable() -> None:
    import code  # noqa: F401
