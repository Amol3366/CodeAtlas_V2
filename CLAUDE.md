# CLAUDE.md Agent Entry

This is the Claude entry point for the same coding-agent contract exposed as
`AGENTS.md` / `CLAUDE.md`.

The maintained contract body lives in `AGENTS.md` to avoid duplicated text
drifting. Claude-style agents that discover `CLAUDE.md` first must read
`AGENTS.md` before planning or changing code. Historical citations to
`CLAUDE.md` and `AGENTS.md` refer to the same policy lineage; do not treat this
entry as a separate contract.

## Before Any Task, Read

| File | For |
| --- | --- |
| `AGENTS.md` | **The contract.** Release-blocking; overrides everything below |
| `docs/plans/PLAN.md` | **Live task status** and the append-only handoff log |
| `documentation/PRD.md` | Product scope and non-goals, in plain language |
| `documentation/architecture.md` | Stack, folder structure, data model, core flows |
| `documentation/rules.md` | Constraints — non-negotiable |
| `documentation/phases.md` | Build order, what shipped, what is still open |
| `documentation/design.md` | Required for all UI work |
| `documentation/memory.md` | Prior context, decisions, known issues |

The `documentation/` folder is a navigable summary written for orientation.
`AGENTS.md` and `docs/plans/PLAN.md` remain authoritative; where a summary and
an authority disagree, the authority wins and the summary is the bug.

Update `documentation/memory.md` at the end of every task, and append — never
rewrite — the handoff entry in `docs/plans/PLAN.md`.
