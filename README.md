# x402-cms

x402-paid CMS — agent-oriented content delivery with HTTP 402 micropayments. **Free for humans, paid for agents.**

[日本語版](README.ja.md)

## Concept

Same URL, different render based on the requester:

- **Human (browser) access** → free HTML
- **AI agent access** → 402 Payment Required, pay via x402, JSON response

Reference implementation of "Agent-oriented CMS" — a category that monetizes agentic access while keeping human access free, embodying the ad-funded → agent-paid transition that protocols like x402 enable.

## Initial use case: x402 dev digest

A weekly digest of the x402 ecosystem — merged PRs, open design discussions, X posts from builders, and signals from the Japanese community — delivered for both human readers and AI agents.

## Tech stack

- FastAPI (Python 3.11+)
- [`python/x402`](https://github.com/x402-foundation/x402/tree/main/python/x402) (server SDK, scheme: `exact/evm`)
- Cloud Run (hosting)
- Firestore (DB)
- Cloud Scheduler + Cloud Run jobs (indexers)
- [`xurl`](https://github.com/xdevplatform/xurl) (X API CLI for the X indexer)

## Status

**Phase 0** — minimal endpoint working on Base Sepolia testnet.

## Setup (Phase 0)

**Prerequisites:** [`uv`](https://docs.astral.sh/uv/) installed, Python 3.11+.

```bash
uv sync
cp .env.example .env  # Set EVM_ADDRESS to your Base Sepolia testnet address
uv run uvicorn app:app --host 0.0.0.0 --port 4021 --reload
```

Verify the payment flow:

```bash
# Free landing endpoint — should return 200 OK
curl http://localhost:4021/

# Paid endpoint — should return 402 Payment Required
# with a `payment-required` header containing the x402 payload
curl -i http://localhost:4021/digest/test
```

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for the full system overview, including:

- Component diagram (target state)
- Request sequence (human vs agent)
- Phase 0 minimal flow
- Data flow (vault → publish → Firestore → render)
- Public / private layer separation

## License

MIT
