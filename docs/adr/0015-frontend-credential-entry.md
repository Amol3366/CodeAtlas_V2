# ADR-0015: The OpenAI API key is entered in Settings and stored by the OS

- Status: accepted
- Date: 2026-08-06
- Decision owners: user/product and implementing agent
- Supersedes: none (extends ADR-0011 and ADR-0012)

## Context

Every provider decision is made in Settings except the one that makes any of
them work. Enabling OpenAI embeddings or OpenAI answer generation required
leaving the application, finding `.env` in the project folder, knowing the
variable name, and restarting the server.

The argument for changing it is not convenience. `.env` is a plaintext file
inside a project folder, and that is how credentials actually leak: committed
by accident, copied when a folder is duplicated, opened during a screen share,
included when someone zips a directory to send it somewhere. A credential
disclosed to a third party is the one Phase 7 failure that cannot be undone —
the reasoning `semantic/redaction.py` already opens with.

Two facts about the code shaped what was possible.

**The key was read from `os.environ` in four separate places:** embedding
provider construction and embedding availability (`semantic/providers.py`),
answer request authorization (`generation/openai_provider.py`), and answer
availability (`generation/factory.py`). Four readers means four chances for one
to miss a new source.

**`.env` is applied by mutating the process environment.** `load_env_file()`
writes into `os.environ` for every key the real environment has not already
set. That is how the key reached all four readers, and it is also a weakness:
CodeAtlas invokes Git through a subprocess adapter, and a child process
inherits its parent's environment.

## Decision

Store the key in the Windows Credential Manager, machine-wide, resolved through
one function, with `.env` retained as a fallback.

- **Storage is the Credential Manager, not SQLite.** Access is `ctypes` against
  `advapi32` (`CredWriteW`/`CredReadW`/`CredDeleteW`), target
  `CodeAtlas/OPENAI_API_KEY`, type `CRED_TYPE_GENERIC`, persistence
  `CRED_PERSIST_LOCAL_MACHINE` so the entry is scoped to the current user on
  this machine and does not roam. No new dependency: `ctypes` is stdlib.
- **Scope is machine-wide.** An API key identifies a billing account, not a
  repository policy. Per-repository opt-in still decides whether any provider
  may be used, so a stored key enables nothing on its own.
- **Precedence is credential store → `.env`**, the same ladder ADR-0014
  established for the embedding model.
- **`resolve_openai_api_key()` is the only place a caller learns the key**, and
  it never writes the resolved value back into `os.environ`.
- **`GET /v1/credentials` reports status only** — `configured`, `source`,
  `store_available` — and `PUT`/`DELETE /v1/credentials/openai` are write-only.
- **Non-Windows degrades to `.env`.** `UnavailableCredentialStore` reads as
  empty and refuses writes rather than dropping them silently.

## Alternatives

**A DPAPI-encrypted column in SQLite.** Simpler, one artifact, and the
ciphertext is undecryptable by another user or machine. Rejected because
`create_backup()` copies the database and that file is also what a user attaches
to a bug report. Putting key material there — even encrypted — makes the
Section 12.5 export and bundle clauses a matter of remembering to redact rather
than a structural fact.

**A DPAPI-encrypted file beside the database.** Keeps the secret out of the
database while staying simple, but adds a second artifact that backup, restore,
deletion, and packaging must all reason about, and none of them do today.

**Replacing `.env`.** Rejected: it breaks scripted and headless use, and the
project-folder rule is a Section 4.4 control with its own reason to exist.

**Masking the key in `GET` — showing the last four characters.** Rejected. A
suffix is still key material, and a response body is logged by intermediaries,
pasted into bug reports, and screenshotted. Section 12.5 carves out no
exception for part of a secret. `configured` plus `source` answers every
question a user has about their own credential.

**Per-repository credentials.** Rejected as scope: it multiplies stored secrets
and re-entry burden to serve a case nobody asked for.

## Consequences

Positive: the key is enterable where every other provider decision is made, it
is out of a plaintext file, and a single resolution point means a future source
is added in one place rather than four.

Negative: **a backup no longer carries the credential.** Restoring a database
onto a different machine or user account means entering the key there. This is
correct, and it is a change in expectation, so it is documented in
`docs/operations/backup-and-restore.md` rather than left to be discovered.

`.env` remains supported, and a `.env` key is reported as such so a user whose
saved key is shadowed can see it rather than guess.

## Security and Privacy

**This does not protect the key from a local attacker, and the record should
not imply otherwise.** The Credential Manager is user-scoped: any code running
as that user can read the entry back, including CodeAtlas, which is the point.
Malware running as the user can read it too — as it could read `.env`, the
process environment, or the memory of the running server.

What it does is remove the key from a plaintext file inside a project folder.
That is a real reduction in the way credentials are actually disclosed, and it
is the whole claim.

The resolved key is never published to `os.environ`, so it is not inherited by
the Git subprocesses CodeAtlas spawns. This is asserted by
`test_resolution_never_publishes_the_key_to_the_environment` and by
`tests/security/test_credential_confinement.py`, the second of which was
strengthened after a mutation showed the first version of it passed against a
deliberately leaking resolver.

No response, log record, database file, or diagnostics payload contains the
value; the contract test asserts the exact response key set, so adding a masked
field later fails the suite rather than passing review.

## Migration and Rollback

No migration. Nothing is stored in SQLite, so `SCHEMA_VERSION` stays at **14**
and `contract_version` stays at **`1.1`** — three additive endpoints and no
change to any existing response.

Rollback for a user: clear the key in Settings, which restores `.env` as the
source. Rollback of the feature: the endpoints and the store module are
additive and removable without touching stored data, because there is none.

## Approval

Approved by the user on 2026-08-06, in the brainstorming session recorded at
`docs/superpowers/specs/2026-08-06-frontend-credential-entry-design.md`. Scope
approved: Credential Manager storage, machine-wide, store-over-`.env`
precedence, and no masking in any response.
