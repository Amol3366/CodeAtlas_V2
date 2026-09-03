# MCP Readiness Implementation Plan

Status: **proposed — NOT approved, and no task may start.**
Date: 2026-09-04
Design: `docs/superpowers/specs/2026-09-04-mcp-readiness-design.md`
Author: Claude Code `claude-opus-5`

`docs/plans/PLAN.md` rule 11: a task in a plan the user has not approved stays
`ready` and MUST NOT move to `in_progress`. Nothing here is boarded until the
user approves this document.

## Global Constraints

- **No new tools, no transport change.** Anything beyond stdio is §25 network
  exposure. The 22 registered tools are the Phase 3 set and cover §13.
- **No version constant moves and no reindex.** Nothing here touches parsing,
  chunking, resolution or storage. If a task appears to need a bump, stop and
  ask — that is a different plan.
- **`contract_version` stays `1.1` and `TOOL_SCHEMA_VERSION` stays `1.0`.** No
  payload shape changes. MC-02 changes *which* failures produce an envelope,
  not the envelope.
- **Test-first, and mutation-check every guard.** Behaviour that already works
  produces tests that pass whether or not they assert anything.
- **Never edit the tree while a gate runs.**

## Premises, checked rather than assumed

Each was verified on 2026-09-04. A plan built on a stale premise is this
project's most-repeated failure, so these carry their evidence.

| Premise | Checked | Result |
| --- | --- | --- |
| 22 tools are registered | `build_registry().names` | **true**, 22 |
| Transport is stdio only | `mcp/__init__.py`, `server.py:99` | **true** |
| No client configuration exists anywhere | `ls .mcp.json`, grep `codeatlas-mcp` | **true** — only `pyproject.toml`, one ADR, one phase plan, `PLAN.md` |
| No `docs/operations/mcp.md` | `ls docs/operations/` | **true** — 15 docs, none for MCP |
| A handler exception escapes the envelope | read `tools.py:147-165`, then **ran it** | **true** — `analyze_working_tree` raised `ValidationError` through the boundary |
| The preflight defect reached MCP | ran the tool on unmodified gson | **true before `8b267d6`, fixed now** |

## File Structure

```text
docs/operations/mcp.md                     # new (MC-03)
src/codeatlas/mcp/tools.py                 # changed (MC-02)
tests/unit/test_mcp_tool_boundary.py       # new (MC-04)
docs/plans/PLAN.md                         # handoff (MC-05)
documentation/memory.md                    # updated (MC-05)
README.md                                  # MCP section gains the config (MC-03)
```

---

### Task MC-01: Drive it from a real client, and record what happens

**Status:** `ready` (blocked on approval)
**Dependencies:** none
**Deliverable: a written record, not a code change.**

Connect a real MCP client to `codeatlas-mcp` and capture, verbatim:

1. the client configuration that worked, including the exact `command` and
   `args` — `uv run codeatlas-mcp` versus the console script versus the
   packaged binary are three different answers and only one needs to be true;
2. the handshake and the tool listing as the client sees it, with the count;
3. one **read-only** call end to end against a real repository —
   `resolve_symbol` or `search_text` against the cached gson checkout at
   `%LOCALAPPDATA%\CodeAtlas\real-repos\gson`;
4. one **deliberate failure** — an unknown `repository_id` — to see what an
   agent actually receives.

**Why this is first.** It is the only task that can invalidate the others. If a
client cannot complete a handshake, MC-02 through MC-04 document something that
does not work.

**Do not fix anything found here.** Record it and stop. A defect found in MC-01
is scoped into MC-02 or becomes its own task with the user's agreement — the
alternative is a task that quietly becomes three.

**Verification:** the record exists and names the client and version. There is
no assertion to run; that is the point of the task.

**Note the database.** The MCP server opens the real database by default
(`CODEATLAS_EPHEMERAL` governs `serve` only, ADR-0040). Use `--db` or an
ephemeral path so this does not register repositories into the user's real
store.

---

### Task MC-02: No handler failure escapes the envelope

**Status:** `pending` (MC-01 may change its scope)
**Dependencies:** MC-01

**Test first.** `tests/unit/test_mcp_tool_boundary.py`: register a tool whose
handler raises a non-`CodeAtlasError`, call it through `ToolRegistry.call`, and
assert an envelope is returned rather than the exception propagating. **Watch it
fail** before changing `tools.py`.

Then widen the dispatch catch:

- `CodeAtlasError` → its own code, message and `retryable`, unchanged;
- any other `Exception` → `INTERNAL_ERROR`, `retryable=False`, and a
  **generic** message. **Do not forward the exception text**: §4.4 forbids
  leaking absolute local paths, and a pydantic `ValidationError` renders the
  whole input value.

**A broad `except` is what `rules.md` forbids, and this is the stated
exception.** The comment at the call site must say why: this is an adapter
boundary, the same role `api/` plays for HTTP, and the alternative is not
"handle it properly" but "crash the agent's session". Reviewers should be able
to see the rule was considered, not bypassed.

**Mutation checks:**

| Mutation | Must fail |
| --- | --- |
| revert to `except CodeAtlasError` | the new boundary test |
| forward `str(error)` into the envelope | a test asserting the message carries no path and no input value |
| return `retryable=True` for `INTERNAL_ERROR` | the retryability assertion |

**Verification:** `pytest tests/unit/test_mcp_tool_boundary.py`, then the
contract suites — `pytest tests/contract -q` — because the envelope is a
published shape.

---

### Task MC-03: `docs/operations/mcp.md`, and the README stanza

**Status:** `pending`
**Dependencies:** MC-02 (it documents the error contract MC-02 changes)

Write the operations document the other fifteen surfaces have. Sections:

- **What it is** — stdio only, no port, launched by the client.
- **Configuring a client** — the exact stanza from MC-01, working, not invented.
- **The tools** — derived from `build_registry()`, never transcribed. The README
  already learned this: `trace_flow` fell out of a hand-copied list because it
  is the one tool built from a loop rather than a literal `name=`.
- **The error envelope** — the shape, and that every failure produces one.
- **What CodeAtlas will not tell you.** The section that matters most for an
  agent, because an agent reads neither `AGENTS.md` §5 nor the README:
  - Java, Go, Rust and Scala have **no test edges, no route detection, and no
    configuration or schema edges**, so `get_related_tests` returning nothing
    for a Java symbol means *not analysed*, not *not tested*;
  - C#, Kotlin, Ruby, PHP, Swift and C/C++ yield **zero symbols**;
  - a `semantic_candidate` is never a fact;
  - an abstention is a successful outcome.
- **The database it opens**, and how to point it elsewhere.

**Verification:** every command and tool name in the document is executed or
derived, not copied from prose. The README's MCP section gains the config
stanza and a link.

---

### Task MC-04: Guard the boundary property

**Status:** `pending`
**Dependencies:** MC-02

A guard that iterates **every** tool in `build_registry()`, forces its handler
to raise, and asserts an envelope — so the property holds for tools that do not
exist yet. Derived from the registry by iteration, never a hand-listed set:
that list-that-must-be-extended is the defect class this project keeps paying
for.

**Verification:** mutation — revert MC-02 and watch the guard fail for every
tool, not just the one MC-02's own test covers.

---

### Task MC-05: Record it

**Status:** `pending`
**Dependencies:** MC-01 to MC-04

Handoff in `docs/plans/PLAN.md`, `documentation/memory.md` updated. Record what
MC-01 found, including anything that did not work — especially anything that
did not work, since MC-01 is the first time this surface has been driven.

If MC-01 surfaced something out of scope, it becomes a Deferred Register row
with a named trigger, not a silent omission.

---

## Self-Review

**What this plan is likely to get wrong.**

- **MC-01 may find the console script is not launchable as configured.** `uv run
  codeatlas-mcp` depends on the working directory; a client launching it from
  elsewhere may not resolve the environment. That would make MC-01's deliverable
  a *fix* rather than a record, which is a scope change and needs the user.
- **The estimate that MC-02 is contained.** It looks like one function. This
  project's record on "it's one function" is poor — ADR-0069 took three fixes,
  each revealing the next. If widening the catch surfaces handlers that were
  relying on propagation, stop and report.
- **MC-03 will be tempted to document the ideal rather than the actual.** The
  "what it will not tell you" section is only worth writing if it is checked
  against the engine's behaviour on a real repository.

**What is deliberately absent.** No new tools, no transport change, no fix for
the symbol-id transfer defect, no performance work. Each is a separate decision
and folding any of them in here would make this plan unreviewable.
