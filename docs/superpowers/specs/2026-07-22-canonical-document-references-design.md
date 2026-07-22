# Canonical Document References Design

## Goal

Make `AGENTS.md` and `BLUEPRINT.md` the only canonical filenames referenced
throughout the repository.

## Scope

- Replace every textual reference to `CLAUDE.md` with `AGENTS.md`.
- Replace every textual reference to
  `CODEATLAS_LOCAL_WINDOWS_BLUEPRINT.md` with `BLUEPRINT.md`.
- Change the heading inside `AGENTS.md` from `CLAUDE.md` to `AGENTS.md`.
- Update Markdown links, documentation, source and test docstrings, comments,
  scripts, configuration files, and the repository tree in `BLUEPRINT.md`.
- Keep the existing `BLUEPRINT.md` filename unchanged.
- Do not alter generated, binary, cache, virtual-environment, or Git metadata.

## Method

Apply exact filename replacements only. Do not rewrite surrounding prose or
change section references. This keeps the change mechanical and avoids changing
the meaning of documentation or code.

## Verification

1. Search the repository, excluding `.git`, caches, and dependency artifacts,
   and confirm that neither old filename remains.
2. Confirm that references to `AGENTS.md` and `BLUEPRINT.md` resolve to existing
   files.
3. Run Ruff, formatting checks, mypy, and the complete pytest suite.
4. Report every modified file to the user.

## Non-Goals

- Renaming `BLUEPRINT.md`.
- Changing product behavior or implementation logic.
- Repairing unrelated staged or untracked changes.
- Committing unrelated work from the existing dirty worktree.
