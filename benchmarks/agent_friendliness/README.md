# Agent-friendliness benchmark

R0 compares the current free HTML and paid-agent JSON representations while
holding the source snapshot, model, effort, prompt, profile digest, and tool
policy constant. Raw captures, private profiles, transcripts, and unblinding
keys belong under `benchmark_artifacts/` and are ignored by git.

The three-step Experiment A workflow is:

```text
uv run python -m code.benchmark capture ...
uv run python -m code.benchmark run-arm --arm H ...
uv run python -m code.benchmark run-arm --arm J ...
```

`run-pair` runs the two fresh contexts in a seeded order and creates the blind
packet. `2026-W28` is rejected from formal scoring by the harness.
