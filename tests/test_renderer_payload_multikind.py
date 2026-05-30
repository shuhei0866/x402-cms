"""Tests for the active / new PR and issue keys in the agent JSON.

The paid payload gained `active_prs`, `new_prs`, and `issues` as
full-row lists alongside `merged_prs`. They serialise in JSON mode
(datetimes → strings) so the whole payload round-trips through
`json.dumps`. The exact top-level key set is pinned separately in
`test_renderer_payload`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from code.renderers.digest import DigestBundle, render_agent_payload
from code.schemas.issue import IssueRecord
from code.schemas.pr import PRRecord

D = datetime(2026, 5, 7, tzinfo=timezone.utc)


def _active(number: int) -> PRRecord:
    return PRRecord(
        repo="x402-foundation/x402",
        pr_number=number,
        title="wip",
        author="a",
        url="https://github.com/x402-foundation/x402/pull/1",
        week="2026-W19",
        status="open",
        kind="active",
        updated_at=D,
        comments=7,
    )


def _new(number: int) -> PRRecord:
    return PRRecord(
        repo="x402-foundation/x402",
        pr_number=number,
        title="new",
        author="a",
        url="https://github.com/x402-foundation/x402/pull/2",
        week="2026-W19",
        status="open",
        kind="new",
        created_at=D,
    )


def _issue(number: int) -> IssueRecord:
    return IssueRecord(
        repo="x402-foundation/x402",
        issue_number=number,
        title="disc",
        author="a",
        url="https://github.com/x402-foundation/x402/issues/50",
        week="2026-W19",
        state="open",
        kind="active",
        comments=12,
        updated_at=D,
    )


def _bundle(**kw) -> DigestBundle:
    return DigestBundle(
        week="2026-W19",
        repo="x402-foundation/x402",
        prs=[],
        x_posts=[],
        cross_references=[],
        active_prs=kw.get("active_prs", []),
        new_prs=kw.get("new_prs", []),
        issues=kw.get("issues", []),
    )


class TestPayloadMultiKind:
    def test_active_and_new_prs_listed_as_full_rows(self) -> None:
        payload = render_agent_payload(
            _bundle(active_prs=[_active(2)], new_prs=[_new(3)])
        )
        assert payload["active_prs"][0]["pr_number"] == 2
        assert payload["active_prs"][0]["kind"] == "active"
        assert payload["new_prs"][0]["pr_number"] == 3
        assert payload["new_prs"][0]["kind"] == "new"

    def test_issues_listed_as_full_rows(self) -> None:
        payload = render_agent_payload(_bundle(issues=[_issue(50)]))
        assert payload["issues"][0]["issue_number"] == 50
        assert payload["issues"][0]["comments"] == 12

    def test_datetimes_serialise_as_strings(self) -> None:
        payload = render_agent_payload(
            _bundle(active_prs=[_active(2)], issues=[_issue(50)])
        )
        assert isinstance(payload["active_prs"][0]["updated_at"], str)
        assert isinstance(payload["issues"][0]["updated_at"], str)

    def test_payload_round_trips_through_json_dumps(self) -> None:
        payload = render_agent_payload(
            _bundle(active_prs=[_active(2)], new_prs=[_new(3)], issues=[_issue(50)])
        )
        text = json.dumps(payload)
        assert '"active_prs"' in text
        assert '"new_prs"' in text
        assert '"issues"' in text
