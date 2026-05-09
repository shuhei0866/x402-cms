# Contributing to x402-cms

## Setup

1. Install [`uv`](https://docs.astral.sh/uv/).
2. Install dependencies and dev tools:
   ```bash
   uv sync
   ```
3. Configure environment:
   ```bash
   cp .env.example .env
   # Edit .env to set EVM_ADDRESS (Base Sepolia testnet for Phase 0).
   # ANTHROPIC_API_KEY is optional; required only for the Layer 2 semantic guard.
   ```
4. Install the pre-commit hook:
   ```bash
   uv run pre-commit install
   ```

## Running the server

```bash
uv run uvicorn code.server.main:app --host 0.0.0.0 --port 4021 --reload
```

Verify Phase 0:

```bash
curl http://localhost:4021/                  # 200 OK
curl -i http://localhost:4021/digest/test    # 402 Payment Required
```

## Pre-commit hooks (two layers)

The repository ships two pre-commit guards. **Both default to no-ops** until you configure their private inputs locally.

### Layer 1 — Regex pattern guard

Loads patterns from `.git/hooks/personal-patterns.local.txt` (gitignored). Add one regex per line; lines starting with `#` are comments. The script ships with no patterns.

Example contents (kept on your machine only):

```
# patterns blocked from staging
my-internal-codename
some-private-handle
```

### Layer 2 — LLM semantic guard

Reads its system prompt from `prompts/semantic_check_system.md` (gitignored). Without that file, or without `ANTHROPIC_API_KEY`, the hook is a no-op.

Bootstrap a private prompt by copying the example:

```bash
cp prompts/semantic_check_system.example.md prompts/semantic_check_system.md
# Edit prompts/semantic_check_system.md to reflect what you want to detect.
```

The prompt itself can encode patterns you would not want to commit, which is why it is intentionally kept private.

### Bypass

When a guard misfires and the commit is intentional, bypass with:

```bash
git commit --no-verify
```

## Style

- English-primary documentation (Japanese parallels live alongside as `*.ja.md`).
- Code comments, docstrings, commit messages, and PR / issue descriptions in this repo are written in English.
- See [`CLAUDE.md`](CLAUDE.md) for the full conventions.

## License

MIT
