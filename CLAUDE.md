# x402-cms — Project Instructions

## Audience

This repository is a public reference implementation of an **Agent-oriented CMS** built on the x402 protocol. Intended audience:

- x402 maintainers and contributors reading it as a Python-side example
- OSS contributors exploring agent-oriented content delivery patterns
- Japanese developers in the x402 / agentic-commerce ecosystem

## Documentation policy

**English-primary, Japanese parallel.**

- Main docs (`README.md`, `docs/architecture.md`, `CONTRIBUTING.md`, future `CHANGELOG.md`) are written in English
- Japanese versions live alongside as `README.ja.md`, `docs/architecture.ja.md`, etc.
- Code comments, docstrings, commit messages, and issue / PR descriptions on this repo: **English**

## Code conventions

- Python 3.11+
- FastAPI as the web framework
- `python/x402` (>= 2.9.0) as the payment SDK
- `exact/evm` scheme on Base Sepolia (testnet) → Base (mainnet, Phase 5)
- `uv` for dependency management
- Server entrypoint: `code/server/main.py` (`create_app()` factory + lifespan)

## Architecture

See [`docs/architecture.md`](docs/architecture.md). The core pattern: **same URL, different render based on User-Agent**. Free HTML for humans, paid JSON for agents via HTTP 402 + x402 protocol.

## Phase progression

| Phase | Scope |
|---|---|
| 0 | Minimal endpoint, hardcoded JSON, testnet — **done** |
| 1 | Weekly digest with GitHub source, dual render (human HTML + agent JSON) |
| 2 | X integration via xurl |
| 3 | Japanese community section, peer cross-reference network |
| 4 | Curator commentary layer (vault → publish → Firestore) |
| 4.5 | Agent-friendly advantage benchmark (HTML vs paid JSON, before mainnet) |
| 5 | Mainnet migration on Base, batch-settlement scheme |
| 6 | Archive, search, SEO |

## Public / private separation

The code is public; the curator's editorial layer is private (gitignored):

- `config/tracked_handles.yaml`
- `config/importance_rules.yaml`
- `prompts/commentary_template.md`
- `prompts/recommendation_prompt.md`
- `prompts/semantic_check_system.md` (the private input for the Layer 2 pre-commit guard)
- `.git/hooks/personal-patterns.local.txt` (the private input for the Layer 1 pre-commit guard)
- `data/source/`, `data/views/`
- `.env`

This separation keeps the architecture reproducible as an OSS reference while protecting the curator's editorial layer. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for setup details.
