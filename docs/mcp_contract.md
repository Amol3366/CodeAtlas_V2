# MCP Tool Contract (Phase 0 draft)

The MCP server (`src/codeatlas/delivery/mcp_tools.py`) is a **thin adapter over
the same application services** used by REST/CLI — never a second implementation
(CLAUDE.md §4, §11). All tools return stable JSON with evidence IDs matching
`src/codeatlas/contracts.py`.

## Required tools (Blueprint §6.3)

| Tool | Input (key fields) | Output | Phase |
|---|---|---|---|
| `register_repository` | `path`, `name?` | repository id, status | 7 |
| `get_repository_status` | `repository_id` | snapshot + index status | 7 |
| `resolve_symbol` | `repository_id`, `symbol` | EvidenceItem(s) | 7 |
| `search_code` | `repository_id`, `query`, `kind?` | EvidenceItem[] | 7 |
| `find_callers` | `repository_id`, `symbol`, `max_depth?` | EvidenceItem[] w/ relation_path | 7 |
| `find_dependencies` | `repository_id`, `symbol`, `max_depth?` | EvidenceItem[] | 7 |
| `find_related_tests` | `repository_id`, `symbol` | EvidenceItem[] (stub-honest until Phase 9) | 7/9 |
| `find_related_documents` | `repository_id`, `symbol` | EvidenceItem[] (stub-honest until Phase 9) | 7/9 |
| `analyze_working_tree` | `repository_id`, `base` | ChangeAnalysis + Finding[] | 10 |
| `analyze_commit_range` | `repository_id`, `base`, `target` | ChangeAnalysis + Finding[] | 10 |
| `check_architecture_rules` | `repository_id`, `rules_path?` | Finding[] | 9 |
| `get_evidence` | `evidence_id` | EvidenceItem | 7 |
| `build_verified_context` | `repository_id`, `question`, `token_budget?` | QueryResponse | 7 |

## Contract rules

- Every output carries: repository, snapshot, file, symbol, lines, confidence,
  derivation, warnings.
- `MAY_CALL` edges are never presented as `CALLS`.
- Test tools never claim behavioral coverage — only "test exists" /
  "test references symbol".
- Errors map to MCP error objects from `domain/errors.py` (stable codes).
- The LLM (when enabled) receives verified evidence only and no tools
  (prompt-injection & §12 rules).
