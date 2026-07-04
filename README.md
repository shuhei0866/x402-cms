# x402-cms

x402-paid CMS — agent-oriented content delivery with HTTP 402 micropayments. **Free for humans, paid for agents.**

[日本語版](README.ja.md)

## Concept

Same URL, different render based on the requester:

- **Human (browser) access** → free HTML
- **AI agent access** → 402 Payment Required, pay via x402, JSON response

Reference implementation of "Agent-oriented CMS" — a category that monetizes agentic access while keeping human access free, embodying the ad-funded → agent-paid transition that protocols like x402 enable.

## Initial use case: x402 dev digest

A weekly digest of the x402 ecosystem — merged / active / newly-opened PRs, live issue discussions, X posts from builders, and signals from the Japanese community — served at `/digest/{YYYY-Www}` for both human readers and AI agents.

The human view is built for weekly review, not just display:

- **This week at a glance** — a first-view dashboard: who moved (per-author activity roll-up, bots folded into a footnote), what's hot (PRs and issues in one comment-count ranking), where the talk is (topic / cluster / keyword distributions)
- **Inverted-pyramid sections** — live discussions read first, most-discussed first; already-closed newcomers and reply tweets fold into `<details>` (folding hides, it never drops)
- **Navigation** — a section nav with stable ids and adjacent-week links close the browse loop

Every ordering and folding rule is mechanical: reply-or-not, open-or-closed, comment counts, recency. Which signals count as which topic lives in a curated mapping (`config/topics.yaml`, gitignored; `config/topics.example.yaml` ships as a working template) — the mapping table is the editorial act, the renderer only counts. Engagement metrics (likes) are deliberately not a sort key: they track follower count, not signal.

## Tech stack

- FastAPI (Python 3.11+)
- [`python/x402`](https://github.com/x402-foundation/x402/tree/main/python/x402) (server SDK, scheme: `exact/evm`, Base Sepolia)
- Pico CSS classless build, vendored — the markup stays class-free semantic HTML
- Cloud Run Service (render) + Cloud Run Jobs (indexers), on weekly + daily Cloud Scheduler crons
- Firestore (4 collections: PRs, issues, X posts, commentary)
- httpx against the GitHub Search API and X API v2 (no CLI dependencies in the image)

## Status

Phases 0–4 are in production on **Base Sepolia testnet**: dual render with real settlement, weekly + daily indexers (PRs / issues / X posts), the curated commentary pipeline (vault → publish → Firestore), and the information-designed human view. Phase 5 — Base mainnet and the batch-settlement scheme — is the remaining roadmap item.

## Setup

**Prerequisites:** [`uv`](https://docs.astral.sh/uv/) installed, Python 3.11+.

```bash
uv sync
cp .env.example .env   # set EVM_ADDRESS to your Base Sepolia address

# Optional: your own curation (both files are gitignored)
cp config/tracked_handles.example.yaml config/tracked_handles.yaml
cp config/topics.example.yaml config/topics.yaml

HANDLES_CONFIG_PATH=config/tracked_handles.yaml \
TOPICS_CONFIG_PATH=config/topics.yaml \
uv run uvicorn code.server.main:app --host 0.0.0.0 --port 4021 --reload
```

Without the two config env vars the server still boots — the cluster sections render their explicit empty states and the glance block says "no topics config loaded". Degraded modes are visible, never silent.

Verify the dual render:

```bash
# Free landing endpoint — 200 OK
curl http://localhost:4021/

# Human view — 200 OK, HTML
curl -A "Mozilla/5.0" http://localhost:4021/digest/2026-W27

# Agent view — 402 Payment Required, with a `payment-required`
# header carrying the x402 payload
curl -i http://localhost:4021/digest/2026-W27
```

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for the full system overview, including:

- Component diagram
- Request sequence (human vs agent)
- Data flow (indexers → Firestore → render; vault → publish → Firestore)
- Deploy topology (Service, Jobs, Schedulers, Secret Manager)
- Public / private layer separation

## License

MIT. The vendored Pico CSS build keeps its own MIT copyright header.
