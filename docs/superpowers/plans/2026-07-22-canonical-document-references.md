# Canonical Document References Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `AGENTS.md` and `BLUEPRINT.md` the only canonical document filenames referenced throughout CodeAtlas.

**Architecture:** Perform two exact, byte-preserving textual substitutions across the UTF-8 text files identified by Ripgrep. Keep the canonical files in place, update the design specification so it does not retain legacy literals, and verify both repository-wide absence of legacy references and project health.

**Tech Stack:** PowerShell, Ripgrep, .NET UTF-8 file APIs, Ruff, mypy, pytest, uv.

## Global Constraints

- Keep the existing filename `BLUEPRINT.md` unchanged.
- Replace references only; do not change product behavior or implementation logic.
- Do not touch `.git`, `.venv`, caches, generated files, binaries, or `uv.lock`.
- Preserve each file's existing line endings and surrounding prose.
- Do not commit in the current commit-less dirty worktree; report modified files instead.

---

### Task 1: Replace Legacy Document References

**Files:**
- Modify: `AGENTS.md`
- Modify: `BLUEPRINT.md`
- Modify: `README.md`
- Modify: `apps/api/main.py`
- Modify: `apps/cli/main.py`
- Modify: `config/default.yaml`
- Modify: `config/logging.yaml`
- Modify: `docs/mcp_contract.md`
- Modify: `docs/non_goals.md`
- Modify: `docs/product_wedge.md`
- Modify: `docs/response_contract.md`
- Modify: `docs/threat_model.md`
- Modify: `migrations/env.py`
- Modify: `scripts/run_dev.ps1`
- Modify: `scripts/setup_windows.ps1`
- Modify: `src/codeatlas/chunking/contracts.py`
- Modify: `src/codeatlas/chunking/persist.py`
- Modify: `src/codeatlas/chunking/token_budget.py`
- Modify: `src/codeatlas/contracts.py`
- Modify: `src/codeatlas/domain/entities.py`
- Modify: `src/codeatlas/domain/enums.py`
- Modify: `src/codeatlas/domain/errors.py`
- Modify: `src/codeatlas/domain/identity.py`
- Modify: `src/codeatlas/indexing/jobs.py`
- Modify: `src/codeatlas/indexing/state_machine.py`
- Modify: `src/codeatlas/logging/setup.py`
- Modify: `src/codeatlas/main.py`
- Modify: `src/codeatlas/parsing/contracts.py`
- Modify: `src/codeatlas/parsing/executor.py`
- Modify: `src/codeatlas/parsing/python/ast_extractor.py`
- Modify: `src/codeatlas/parsing/python/parser.py`
- Modify: `src/codeatlas/parsing/tree_sitter/js_ts_extractor.py`
- Modify: `src/codeatlas/parsing/typescript/parser.py`
- Modify: `src/codeatlas/repositories/git_service.py`
- Modify: `src/codeatlas/repositories/ignore_rules.py`
- Modify: `src/codeatlas/repositories/path_security.py`
- Modify: `src/codeatlas/repositories/scanner.py`
- Modify: `src/codeatlas/repositories/service.py`
- Modify: `src/codeatlas/repositories/snapshot_manager.py`
- Modify: `src/codeatlas/settings/config.py`
- Modify: `src/codeatlas/settings/paths.py`
- Modify: `src/codeatlas/storage/sqlite/engine.py`
- Modify: `src/codeatlas/storage/sqlite/models.py`
- Modify: `src/codeatlas/storage/sqlite/repositories.py`
- Modify: `src/codeatlas/storage/sqlite/writer.py`
- Modify: `tests/evaluation/change_cases.json`
- Modify: `tests/security/test_no_code_execution.py`
- Modify: `tests/unit/test_contracts.py`
- Modify: `tests/unit/test_python_parser.py`
- Modify: `tests/unit/test_state_machine.py`
- Modify: `tests/unit/test_storage_snapshots.py`
- Modify: `tests/unit/test_windows_edge_cases.py`
- Modify: `docs/superpowers/specs/2026-07-22-canonical-document-references-design.md`

**Interfaces:**
- Consumes: existing UTF-8 repository text files and the canonical root files.
- Produces: documentation references that resolve only to `AGENTS.md` and `BLUEPRINT.md`.

- [ ] **Step 1: Run the failing repository-reference check**

```powershell
$legacyAgent = 'CLAUDE' + '.md'
$legacyBlueprint = 'CODEATLAS_LOCAL_WINDOWS_' + 'BLUEPRINT.md'
rg -n --hidden -g '!.git/**' -g '!.venv/**' -g '!uv.lock' "$([regex]::Escape($legacyAgent))|$([regex]::Escape($legacyBlueprint))" .
```

Expected: FAIL as a completion check because matches are reported in `README.md`, `AGENTS.md`, `BLUEPRINT.md`, source docstrings, tests, scripts, configuration, and documentation.

- [ ] **Step 2: Apply exact replacements to matching text files**

```powershell
$legacyAgent = 'CLAUDE' + '.md'
$legacyBlueprint = 'CODEATLAS_LOCAL_WINDOWS_' + 'BLUEPRINT.md'
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$files = rg -l --hidden -g '!.git/**' -g '!.venv/**' -g '!uv.lock' -g '!docs/superpowers/**' "$([regex]::Escape($legacyAgent))|$([regex]::Escape($legacyBlueprint))" .
foreach ($file in $files) {
    $path = (Resolve-Path -LiteralPath $file).Path
    $text = [System.IO.File]::ReadAllText($path)
    $updated = $text.Replace($legacyAgent, 'AGENTS.md').Replace($legacyBlueprint, 'BLUEPRINT.md')
    if ($updated -ne $text) {
        [System.IO.File]::WriteAllText($path, $updated, $utf8NoBom)
    }
}
```

Expected: only the files listed above, except the design specification handled in Step 3, receive mechanical filename substitutions. Existing CRLF/LF characters remain unchanged.

- [ ] **Step 3: Remove legacy literals from the design specification**

Replace the design specification's Scope bullets with this wording:

```markdown
- Replace every reference to the legacy agent-guide filename with `AGENTS.md`.
- Replace every reference to the legacy long-form blueprint filename with
  `BLUEPRINT.md`.
```

Expected: the specification still documents the intent without retaining either legacy filename.

- [ ] **Step 4: Verify the repository-reference check is green**

```powershell
$legacyAgent = 'CLAUDE' + '.md'
$legacyBlueprint = 'CODEATLAS_LOCAL_WINDOWS_' + 'BLUEPRINT.md'
$matches = rg -n --hidden -g '!.git/**' -g '!.venv/**' -g '!uv.lock' "$([regex]::Escape($legacyAgent))|$([regex]::Escape($legacyBlueprint))" .
if ($LASTEXITCODE -eq 1) { 'No legacy document references remain.'; exit 0 }
$matches
exit 1
```

Expected: PASS with `No legacy document references remain.`

- [ ] **Step 5: Verify canonical files and README links**

```powershell
if (-not (Test-Path -LiteralPath 'AGENTS.md')) { throw 'AGENTS.md is missing' }
if (-not (Test-Path -LiteralPath 'BLUEPRINT.md')) { throw 'BLUEPRINT.md is missing' }
rg -n "AGENTS\.md|BLUEPRINT\.md" README.md AGENTS.md BLUEPRINT.md
```

Expected: both files exist; README links and the internal agent/blueprint references use canonical names.

- [ ] **Step 6: Run project verification**

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy src/codeatlas
uv run pytest -q
```

Expected: Ruff passes, formatting is unchanged, mypy reports no issues, and the full pytest suite passes with only the existing environment-dependent symlink skip allowed.

- [ ] **Step 7: Report the exact modified-file set without committing**

```powershell
git diff --name-only
git status --short
```

Expected: the handoff lists every file changed by the canonical-reference replacement and clearly distinguishes pre-existing staged/untracked work. Do not create a commit in this dirty initial repository.
