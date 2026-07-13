"""Typed digest and Codex-event adapter tests for the real R0-A path."""

from __future__ import annotations

import json

from code.benchmark.codex_runner import parse_codex_events
from code.benchmark.digest import freeze_digest_snapshot, thaw_digest_snapshot
from code.renderers.digest import DigestBundle, render_agent_payload, render_html
from code.renderers.digest.topics import TopicRule, XKeywordRule


def test_digest_snapshot_round_trip_preserves_both_renderer_outputs() -> None:
    bundle = DigestBundle(
        week="2026-W27",
        repo="x402-foundation/x402",
        prs=[],
        x_posts=[],
        cross_references=[],
        handle_clusters={"0x_natto": "japan"},
        topic_rules=[TopicRule("protocol", "Protocol", ("core",), ("settlement",))],
        x_keywords=[XKeywordRule("payments", "Payments", ("x402",))],
    )

    snapshot = freeze_digest_snapshot(bundle, published_editions=[], lang="ja")
    thawed, editions, lang = thaw_digest_snapshot(snapshot)

    assert lang == "ja"
    assert render_html(thawed, lang=lang, published_editions=editions) == render_html(
        bundle, lang="ja", published_editions=[]
    )
    assert render_agent_payload(thawed) == render_agent_payload(bundle)


def test_codex_jsonl_parser_collects_usage_and_tool_calls() -> None:
    events = "\n".join(
        (
            json.dumps({"type": "thread.started", "thread_id": "fresh"}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "command_execution", "command": "pwd"},
                }
            ),
            json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 100,
                        "cached_input_tokens": 20,
                        "output_tokens": 30,
                        "reasoning_output_tokens": 4,
                    },
                }
            ),
        )
    )

    parsed = parse_codex_events(events)

    assert parsed == {
        "input_tokens": 100,
        "cached_input_tokens": 20,
        "output_tokens": 30,
        "reasoning_output_tokens": 4,
        "model_calls": 1,
        "tool_calls": 1,
    }
