"""Human discovery routes around the existing dual-render digest."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi.testclient import TestClient

os.environ.setdefault("EVM_ADDRESS", "0x0000000000000000000000000000000000000001")

from code.renderers.digest import DigestBundle, PublishedEdition  # noqa: E402
from code.server import main as server_main  # noqa: E402

BROWSER = {"user-agent": "Mozilla/5.0", "accept-language": "ja-JP"}


def _edition() -> PublishedEdition:
    return PublishedEdition(
        week="2026-W28",
        title="決済の先に残る、運用の設計",
        published_at=datetime(2026, 7, 13, tzinfo=timezone.utc),
    )


def _bundle(week: str, *, content: bool) -> DigestBundle:
    commentaries = []
    if content:
        from code.schemas.commentary import Commentary

        commentaries = [
            Commentary(
                slug="preface",
                week=week,
                week_level=True,
                title="決済の先に残る、運用の設計",
                body_md="body",
                published=True,
            )
        ]
    return DigestBundle(
        week=week,
        repo="x402-foundation/x402",
        prs=[],
        x_posts=[],
        cross_references=[],
        commentaries=commentaries,
    )


def _client(monkeypatch, *, content: bool = True) -> TestClient:
    monkeypatch.setattr(
        server_main, "read_published_editions", lambda **_: [_edition()]
    )
    monkeypatch.setattr(
        server_main,
        "load_digest_bundle",
        lambda week, **_: _bundle(week, content=content),
    )
    return TestClient(server_main.create_app())


def test_browser_root_renders_latest_edition(monkeypatch) -> None:
    client = _client(monkeypatch)
    response = client.get("/", headers=BROWSER)
    assert response.status_code == 200
    assert "決済の先に残る、運用の設計" in response.text


def test_agent_root_keeps_machine_readable_description(monkeypatch) -> None:
    client = _client(monkeypatch)
    response = client.get("/", headers={"user-agent": "python-httpx/0.28"})
    assert response.status_code == 200
    assert response.json()["name"] == "x402-cms"


def test_browser_archive_lists_published_editions(monkeypatch) -> None:
    client = _client(monkeypatch)
    response = client.get("/archive", headers=BROWSER)
    assert response.status_code == 200
    assert "記事一覧" in response.text
    assert "/digest/2026-W28?lang=ja" in response.text


def test_empty_human_week_returns_useful_404(monkeypatch) -> None:
    client = _client(monkeypatch, content=False)
    response = client.get("/digest/2026-W26", headers=BROWSER)
    assert response.status_code == 404
    assert "この週の記事は公開していません。" in response.text
    assert "/archive?lang=ja" in response.text
