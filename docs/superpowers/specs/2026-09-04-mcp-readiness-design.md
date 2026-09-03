# MCP readiness — design

Status: proposed
Date: 2026-09-04
Author: Claude Code `claude-opus-5`
Plan: `docs/superpowers/plans/2026-09-04-mcp-readiness.md`

## The problem

`AGENTS.md` §2 names a coding agent as one of three users, `documentation/PRD.md`
says it "connects over MCP, needs facts it can act on rather than plausible
prose", and the MCP adapter has existed since Phase 3. **Nothing in this
repository has ever driven it from a real client.**

Every other surface has an operations document — `web-application.md`,
`packaging-and-install.md`, `ephemeral-sessions.md`, `end-to-end-tests.md`,
fifteen of them. **MCP has none.** `codeatlas-mcp` appears in `pyproject.toml`,
one ADR, one phase plan and `PLAN.md`; the README lists the 22 tools and never
says how to connect to them. A user or an agent cannot set this up from the
documentation, because the documentation does not exist.

That is the shape this project has repeatedly paid for: **the surface nobody
exercises is where the defect lives.** `-Package` was opt-in and shipped an
artifact to `main` that could not start. `-Semantic` was opt-in and two tracked
baselines sat stale for two days. `check_real_repos.py` was in no gate and its
first gated run found preflight broken on four of five real repositories.

## What is already known to be wrong

Both found 2026-09-04 while investigating, both measured rather than reasoned.

### 1. A handler exception escapes the tool boundary

`ToolRegistry.call` (`src/codeatlas/mcp/tools.py:147`) translates failures into
the envelope in two places, and they do not cover the same thing:

```python
try:
    payload = tool.input_model.model_validate(dict(arguments))
except ValueError as error:            # input validation only
    return _envelope("INVALID_REQUEST", _first_message(error))

try:
    return tool.handler(services, payload)
except CodeAtlasError as error:        # dispatch: CodeAtlasError ONLY
    return _envelope(error.code.value, error.message, error.retryable)
```

Anything a handler raises that is not a `CodeAtlasError` propagates out of the
adapter into the MCP server loop. **Demonstrated**, before the preflight fix:
`analyze_working_tree` against an unmodified gson checkout raised
`ValidationError` straight through the boundary.

That specific trigger is now fixed, and **the hole is not**. `AGENTS.md` §13
requires a tool to "return warnings and unsupported states rather than silently
omitting them", and §12.6 requires one machine-readable error envelope with no
stack traces. An uncaught exception satisfies neither.

**This needs no ruling.** It is a containment fix in one function.

### 2. There is no way to configure a client

No `.mcp.json`, no example client stanza, no `docs/operations/mcp.md`. The
server is stdio-only (`src/codeatlas/mcp/__init__.py`: "No socket is opened and
no port is bound"), which is the right posture for a local-first product and
also means the client must launch the process — so the config is the whole
integration surface, and it is undocumented.

## What this design does NOT decide

**No new tools.** The 22 are the Phase 3 set and they cover §13's required
capabilities. Whether an agent wants a different *shape* — a "before edit" and
"after edit" pair, say — is a product question, and answering it by adding tools
before anyone has driven the existing ones would be the same mistake as
documenting a surface nobody has run.

**No transport change.** Anything beyond stdio is §25 network exposure.

**Not the symbol-id transfer defect.** Recorded 2026-09-04: a same-named sibling
inserted above another transfers the earlier symbol's id. It reaches MCP through
the same analysis path, but closing it needs a new identity input — a
`PARSER_BUNDLE_VERSION` bump and a forced reindex — which is a ruling and does
not belong inside an MCP readiness pass.

## The design

Four pieces, in dependency order. The first is deliberately *not* a code change.

### A. Drive it from a real client, and write down what happens

Before hardening anything, connect a client and record the handshake, the tool
listing, and one read-only call against a real repository. This is the step that
turns "22 tools are registered" into "an agent can use this", and it is the one
most likely to surface something nobody predicted — which is the argument for
doing it first rather than last.

**Acceptance is behavioural, not structural.** `build_registry()` returning 22
names proves the registry; it does not prove a client can list them.

### B. Close the tool boundary

Every handler failure returns the envelope. The catch widens from
`CodeAtlasError` to `Exception`, with a deliberate split:

- a `CodeAtlasError` keeps its own stable code and `retryable` flag;
- anything else becomes `INTERNAL_ERROR`, retryable `false`, with a **generic**
  message. The exception text is not forwarded: §4.4 forbids leaking absolute
  local paths, and a pydantic `ValidationError` renders the entire input value.

A broad `except` is normally what `documentation/rules.md` forbids — "DO NOT use
an empty `except`, a swallowed exception, or a log line as error handling". This
is the documented exception to that rule and must say so at the call site: it is
an **adapter boundary**, the same role `api/` already plays for HTTP, and the
alternative is not "handle it properly" but "crash the agent's session".

### C. The operations document

`docs/operations/mcp.md`, matching the other fifteen: what it is, how to
configure a client, what the tools do, what the error envelope looks like, and —
the part that matters most for an agent — **what CodeAtlas will not tell you**.

An agent acting on a `get_related_tests` result for a Java repository needs to
know there are no test edges for the query-backed tier. That limit is in
`AGENTS.md` §5 and the README, and an agent reads neither.

### D. A guard, so the wiring cannot rot

The registry is already derived (`test_readme_claims.py` counts tools from
`build_registry()`). What is unguarded is the **boundary property**: that no
tool can raise past the envelope. A test that calls every registered tool with a
handler forced to raise, and asserts an envelope comes back, pins B for tools
that do not exist yet.

## Why this order

A is first because it is the only step that can invalidate the others. If a real
client cannot complete a handshake, B/C/D are all documentation of something
that does not work — and this session has already spent a pass writing about a
number nobody had re-derived.

B before C because the operations document describes the error contract, and
writing the document first would describe behaviour that is about to change.

D last because a guard written against unfinished behaviour pins the wrong
thing.

## Open question for the user

**Which client is the target?** The plan assumes Claude Code on this machine,
because it is present and it is the case the PRD describes. If the intended
client is different — another agent runtime, or a generic MCP inspector — the
configuration in step A and the document in step C change, and nothing else
does.
