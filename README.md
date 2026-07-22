# CodeAtlas

**The verified context and change-impact layer for AI-assisted software development.**

CodeAtlas deterministically understands a local repository's structure and Git
changes, then supplies exact, evidence-backed answers (file, symbol, line range,
relation path, confidence, derivation) to developers and coding agents via CLI,
MCP, REST, and JSON/Markdown/SARIF reports.

It is **local-first**, single-user, Windows-first, and **fully useful without
embeddings or an LLM**. The LLM is an optional explanation layer over
deterministically verified evidence — never the repository-understanding system.

> Product wedge:
> `codeatlas impact --base main --working-tree --format markdown`
> → What changed, what can break, which tests/docs are affected, which
> architecture rules are violated — with exact file-and-line evidence.

See [`CLAUDE.md`](CLAUDE.md) for agent guidance and the phase tracker, and
[`CODEATLAS_LOCAL_WINDOWS_BLUEPRINT.md`](CODEATLAS_LOCAL_WINDOWS_BLUEPRINT.md)
for the authoritative product/technical specification.

Phase 0 contract documents live under [`docs/`](docs/). Evaluation fixtures and
benchmark truth live under [`tests/fixtures/`](tests/fixtures/) and
[`tests/evaluation/`](tests/evaluation/).

## Setup

```powershell
uv venv --python 3.12
uv sync --all-extras --group dev
uv run pytest
```

See `scripts/setup_windows.ps1` for a fresh-machine setup.
