# Product Wedge & Scope (accepted — Phase 0)

## Product wedge statement

> **CodeAtlas is the verified context and change-impact layer for AI-assisted
> software development.** It deterministically understands local repository
> structure and Git changes, then supplies exact, evidence-backed answers
> (file, symbol, line range, relation path, confidence, derivation) to
> developers and coding agents.

The first high-value workflow — the wedge:

```powershell
codeatlas impact --base main --working-tree --format markdown
```

→ *What changed, what can break, which tests/docs are affected, which
architecture rules are violated — with exact file-and-line evidence.*

**The MVP is successful even with embeddings and the LLM disabled.** The LLM is
an optional explanation layer over deterministically verified evidence; it is
never the repository-understanding system (CLAUDE.md §1, Blueprint §1.1).

## Supported languages & content (fixed for the MVP)

| Content | Extensions | Classification | Status |
|---|---|---|---|
| Python | `.py`, `.pyi` | source | Required |
| TypeScript | `.ts`, `.tsx` | source | Required |
| JavaScript | `.js`, `.jsx`, `.mjs`, `.cjs` | source | Required |
| Markdown | `.md`, `.markdown` | documentation | Required |
| JSON | `.json` | configuration | Required |
| YAML | `.yaml`, `.yml` | configuration | Required |
| TOML | `.toml` | configuration | Required |

Deferred until the first change-impact benchmark is stable (Blueprint §4.4.5):
TSX framework enrichment, SQL schema semantics, OpenAPI deep analysis, and
additional languages.

## Contract vocabulary (finalized)

- **Symbol types** — `src/codeatlas/domain/enums.py::SymbolType` (Blueprint §4.4.6).
- **Relation types** — `src/codeatlas/domain/enums.py::RelationType` (Blueprint §4.4.7).
- **Evidence / Finding / Response** — `src/codeatlas/contracts.py` (Blueprint §7.6, §10.7, §10.9).

## Deployment profiles (Blueprint §5.4)

1. Deterministic local MVP — embeddings off, answering off. *(default)*
2. Privacy-preserving hybrid — local embeddings, OpenAI answering over a small
   verified evidence bundle.
3. Cloud-assisted opt-in — OpenAI embeddings for changed chunks only + OpenAI
   answering; raw source stays local.
4. Fully local — local embeddings + Ollama answering.
