# CLI Contract (Phase 0 draft)

Typer app: `codeatlas` (`src/codeatlas/main.py`). Every command emits the shared
evidence contract (`src/codeatlas/contracts.py`). Human output is the default;
`--format json` emits machine-readable output on stdout. Diagnostics go to
stderr. Commands are implemented across Phases 7, 8, and 10.

## Commands

| Command | Purpose | Phase |
|---|---|---|
| `codeatlas scan` | Register/rescan a repo; emit deterministic manifest + diagnostics | 7 |
| `codeatlas search` | Exact/fuzzy/lexical search over files, symbols, text | 7 |
| `codeatlas callers` | Inbound `CALLS`/`MAY_CALL` for a symbol, with relation paths | 7 |
| `codeatlas dependencies` | Outbound dependencies for a symbol | 7 |
| `codeatlas impact` 🎯 | Change-impact analysis (the product wedge) | 10 |
| `codeatlas doctor` | Env checks, DB integrity, path issues, index/snapshot status | 7 |

## Representative signatures

```text
codeatlas scan <path> [--name NAME] [--rebuild] [--format human|json]
codeatlas search <query> [--kind files|symbols|text] [--limit N] [--format ...]
codeatlas callers <symbol> [--repo REPO] [--max-depth N] [--format ...]
codeatlas dependencies <symbol> [--repo REPO] [--max-depth N] [--format ...]
codeatlas impact --base <ref> [--target <ref>] [--working-tree] \
                 [--format json|markdown|sarif] [--rules PATH]
codeatlas doctor [--repo REPO]
```

## Exit codes (stable contract)

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Generic runtime error |
| 2 | Usage / invalid arguments (Typer default) |
| 3 | Repository or path error (`RepositoryError` / `PathSecurityError`) |
| 4 | Snapshot not ready / consistency error |
| 5 | Provider/budget error (deterministic fallback still available) |

Errors are typed in `src/codeatlas/domain/errors.py` and mapped to these codes by
the CLI adapter. `impact` never requires embeddings or an LLM.
