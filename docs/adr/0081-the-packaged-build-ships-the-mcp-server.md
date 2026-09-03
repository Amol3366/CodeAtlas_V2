# ADR-0081: The packaged build ships the MCP server as its own executable

- Status: accepted
- Date: 2026-09-04
- Decision owners: user/product (chose the option) and implementing agent
- Supersedes: none

## Context

`AGENTS.md` §2 names a coding agent as one of three users. §13 requires MCP to
wrap the same use cases as the CLI and produce the same evidence model.
`documentation/PRD.md` says the agent "connects over MCP". The adapter has
existed since Phase 3: 22 tools, `TOOL_SCHEMA_VERSION` 1.0, a `codeatlas-mcp`
console script, stdio only.

**The packaged Windows release contained none of it.** `packaging/entry.py`
froze exactly one entry point — `codeatlas.cli.main:main` — so the artifact
shipped `codeatlas.exe` and nothing else. There was no `mcp` subcommand on the
CLI either. An agent using the release the README tells people to unzip and run
with no install and no elevation **could not use MCP at all**; it was
source-checkout-only.

Nothing recorded this. The README's MCP section lists the 22 tools and does not
mention that the packaged build does not contain them, which is worse than the
gap itself: a reader is told about a capability the artifact lacks.

This is the shape this project keeps paying for — the surface nobody exercises
is where the defect lives. `-Package` was opt-in and shipped an artifact that
could not start (ADR-0065). `-Semantic` was opt-in and two tracked baselines
sat stale. `check_real_repos.py` was in no gate, and its first gated run found
preflight broken on four of five real repositories.

## Decision

**The packaged build produces two executables in one shared bundle:
`codeatlas.exe` and `codeatlas-mcp.exe`.**

`packaging/mcp_entry.py` is the second frozen script and calls the same
`codeatlas.mcp.server:main` the console script calls, so a source install and a
packaged install cannot drift. It contains no logic, for the reason
`packaging/entry.py` already states: behaviour living only there would be
behaviour only packaged users get.

The build moves from a command-line PyInstaller invocation to
`packaging/codeatlas.spec`. This is forced rather than preferred:
`pyinstaller a.py b.py` builds **one** program over two scripts, not two
programs. Only a spec can declare two `EXE`s and hand both to one `COLLECT`.
`scripts/build_package.ps1` still owns *what* is built and passes the four data
paths in as environment variables; the spec owns only *how* it is assembled.

**The build verifies the MCP executable by speaking the protocol to it** —
`initialize`, `tools/list`, one call, and one deliberate failure — through
`scripts/verify_mcp_server.py`, which the packaged end-to-end suite reuses so
the build and the gate cannot check different things.

## Alternatives

**A `codeatlas.exe mcp` subcommand.** Less packaging risk: no spec, no second
Analysis. Rejected because it publishes a different surface from the one source
users already have. A client stanza points at `codeatlas-mcp`, which is the
console script name a `pip`/`uv` install provides, and keeping the two identical
is the rule `packaging/entry.py` exists to enforce.

**Ship MCP as a separate distribution or repository.** Both were offered and
declined by the user. A separate repo would make §4.5's "adapters call the same
application services" a pinned version across a release boundary rather than a
guarantee, and would introduce skew between `TOOL_SCHEMA_VERSION` and the
services it wraps.

**Leave it source-only.** Rejected: it makes §13 aspirational for every user of
the shipped artifact.

## Consequences

- **The second executable costs kilobytes of payload and one more PYZ.** The
  bundle is shared through a single `COLLECT`, which is the whole reason both
  go through one, so torch is not duplicated.
- **`--help` cannot verify this executable.** It is a stdio server and would
  block. That forced the protocol check, which is a strict improvement: `--help`
  is exactly what still worked on 2026-08-19 while the artifact was otherwise
  destroyed.
- **stdout is now a protocol channel in a shipped binary.** Any future code that
  prints on import corrupts the JSON-RPC stream. `verify_mcp_server.py` fails on
  non-JSON stdout for that reason, and `mcp_entry.py` says so in its docstring.
- The spec is a new file that must stay in step with the adapters.
  `test_gate_script_invocations.py` was re-pointed at it, keeping its derivation
  from the adapters and its "defining a path is not bundling it" strictness, and
  was mutation-checked after the move.

## Migration and rollback

**None required.** No runtime contract changes: `contract_version` stays `1.1`,
`TOOL_SCHEMA_VERSION` stays `1.0`, `SCHEMA_VERSION` stays 14, and no parser,
chunker or resolver version moves. **No reindex.** Rollback is reverting the
spec and the second entry point; the artifact then contains one executable
again, as before.

## Security and privacy

No new surface. The server remains **stdio only** — no socket, no port — so
this does not touch §25's network-exposure item. It opens the same database the
CLI does, honouring `CODEATLAS_DB_PATH`, and the verification run is pointed at
a throwaway path because `open_services` upgrades whatever it opens.

## Approval

The user chose this option explicitly on 2026-09-04, from four presented
alternatives including a separate distribution and a separate repository, after
being shown that the packaged artifact contained no MCP entry point.

## Outcome

Built and verified 2026-09-04 on a deterministic build: both executables
produced, and `codeatlas-mcp.exe` answered `initialize` with `serverInfo.name`
`codeatlas`, listed **22** tools, returned a result for `list_repositories`,
and produced a `REPOSITORY_NOT_FOUND` **envelope** rather than a crash for an
unknown repository.

**Observed and not attributed:** a build without `-SemanticLocal` carries
`torch`, `lancedb` and `transformers`, because the extras are installed in the
build environment and analysis reaches them. `cli/main.py` already imports
`LazyVectorStore`, so the second entry point does not widen that surface — but
the previous artifact was overwritten before a controlled comparison could be
run, so this is recorded as an observation rather than a finding.
