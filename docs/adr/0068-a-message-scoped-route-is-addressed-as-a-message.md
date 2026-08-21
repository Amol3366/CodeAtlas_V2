# ADR-0068: A message-scoped route is addressed as a message, and an unbuilt endpoint leaves the contract

- Status: **accepted** 2026-08-21
- Date: 2026-08-21
- Decision owners: user/product and implementing agent
- Supersedes: none. Closes the `AGENTS.md` §12 divergence carried since
  2026-08-19 as the last item in the post-ADR-0065 program needing a decision.

## Context

`AGENTS.md` §12 disagreed with the implementation in three places. The
divergence had been recorded twice — in
`docs/superpowers/plans/2026-08-20-remaining-work.md` (P1-C) and in the Active
Work block — as "move the contract, or move the code", with no evidence
attached either way.

Checked against source rather than against the plan that described it:

| Contract §12 | Implementation |
| --- | --- |
| `POST /v1/messages/{id}/retry` | `POST /v1/conversations/messages/{id}/retry` |
| `POST /v1/messages/{id}/feedback` | `POST /v1/conversations/messages/{id}/feedback` |
| `POST /v1/message-runs/{run_id}/cancel` | **matches** |
| `POST /v1/query/stream` | **does not exist** |

**The detail neither record carried is the one that settles it: the nested path
contains no conversation id.** `/v1/conversations/messages/{message_id}/retry`
names `conversations` and then never identifies one. The prefix is inherited
from `APIRouter(prefix="/v1/conversations")` at `conversations.py:40`, not
chosen — the handlers landed in that file and took its prefix with them.

The second half of the diagnosis is the sibling. `cancel` is the third
operation on the same run lifecycle, and it sits at `/v1/message-runs/...`
exactly as the contract says, because it happens to live in `stream.py`, whose
router is prefixed `/v1`. So the implementation was already inconsistent with
itself, and the axis of inconsistency was which file a handler was written in.

**Neither route had a Python test.** `retry` was exercised only through the web
client and a mocked path string in `Thread.test.tsx`; `feedback` had no caller
at all — no web client, no CLI, no test. That is why nothing ever objected.

`POST /v1/query/stream` is a separate question that happens to sit in the same
section: specified in Phase 0, never implemented, and never missed across seven
phases.

## Decision

**1. Move the code, not the contract.** `retry` and `feedback` are served from a
second router, `message_router`, prefixed `/v1/messages`, so they are addressed
by the resource they actually take.

The alternative — amending §12.2 to record the nested paths — would ratify a
path that scopes by a resource it never names, and would leave `cancel`
permanently inconsistent with its two siblings for no reason anyone could state.

**A second router rather than re-prefixing the existing one.** Changing
`conversations.py`'s router to `/v1` would rewrite ten unrelated handlers to
carry `/conversations` in each path, which is the unrelated refactor §4.5
forbids. `stream.py` already demonstrates the pattern: one `/v1`-prefixed router
carrying both a conversation-scoped and a message-scoped path.

**2. Remove `POST /v1/query/stream` from §12.3 rather than build it.** Nothing
has needed it in seven phases. Accept-then-stream (ADR-0008) covers a
conversation turn and `POST /v1/query` covers a one-shot question; a third shape
has no stated need. Keeping a documented endpoint that does not exist is the
defect `SECURITY.md` had until 2026-08-20 — a published claim with nothing
behind it. Adding it later remains available and needs a §25 approval and a
stated need first.

## Alternatives

**Amend §12.2 to match the code.** Zero risk and zero work, and rejected on the
merits above: the shipped path is an artifact of file placement, not a design,
and it already disagrees with `cancel`.

**Leave the divergence open in the Deferred Register.** Rejected because it had
already been carried, unresolved and un-evidenced, since 2026-08-19 as the one
item blocking the close of P1-C. The register's purpose is to give every item a
terminal state.

**Implement `POST /v1/query/stream`.** Rejected: real work with no stated need,
and §25 requires the need before the endpoint rather than after.

**Keep it specified and unbuilt, with a register row.** Rejected for the same
reason the `SECURITY.md` version table was removed rather than annotated. A
reader of §12.3 reads a list of endpoints, not a list of intentions.

## Consequences

**This is a breaking API change, and that is why it needed approval.** Two
published paths stop answering. The blast radius is bounded and was measured
before the change rather than asserted:

- the API is loopback-only, single-user, and has no tagged releases, so there
  is no external consumer that could be broken;
- the only caller of either path was `apps/web`, whose types are generated —
  `scripts/generate_web_types.ps1` regenerated them, and one call site
  (`lib/conversations.ts`) and one mocked path (`Thread.test.tsx`) changed;
- `feedback` had no caller at all.

**`contract_version` stays `1.1`.** This changes where two operations are
addressed, not the shape of any request or response, and the envelope is
untouched. The version is deliberately *not* bumped: it describes the payload
contract that clients parse, and bumping it would tell every consumer their
parsing had changed when it has not.

**Positive, and small.** The two routes now have their first HTTP-level test
coverage, which they lacked entirely. §12 and the implementation agree for the
first time.

**Negative, and stated.** Anyone holding a URL to the old paths — a script, a
saved request, a bookmark — gets `INVALID_REQUEST` with "No such endpoint."
rather than a redirect. No compatibility alias was added, deliberately: an alias
would preserve exactly the shape this record removes, and a deprecation window
has no one to serve on a single-user local product.

## Security and Privacy

None. No new data is read, transmitted, executed, or stored; no trust boundary
moves. The routes bind to the same loopback API with the same auth posture
(none, by documented assumption) and the same error envelope.

## Migration and Rollback

| Item | Change |
| --- | --- |
| `PARSER_BUNDLE_VERSION` | unchanged |
| `RESOLVER_VERSION` | unchanged |
| `CHUNKER_VERSION` | unchanged |
| `SCHEMA_VERSION` | **14, unchanged — no migration** |
| `contract_version` | **`1.1`, unchanged** — see Consequences |

**No stored data changes and no reindex is required.** Nothing persisted refers
to a route path.

**Rollback:** move the two decorators back onto `router`, drop
`message_router` and its `include_router` line, restore the `/v1/query/stream`
line in §12.3, and regenerate the web types. The two-sided tests in
`tests/contract/test_message_routes.py` fail in the opposite direction, which is
what makes the rollback self-checking rather than silent.

## Approval

**Ruled by the user on 2026-08-21**, on both halves, after the divergence was
checked against source and the missing-conversation-id finding was presented:

1. **§12.2 — move the code**, chosen over amending the contract, on the grounds
   that the nested path scopes by a resource it never names and is inconsistent
   with `cancel`.
2. **§12.3 — remove `POST /v1/query/stream` from the contract**, chosen over
   implementing it and over leaving it specified and unbuilt.
