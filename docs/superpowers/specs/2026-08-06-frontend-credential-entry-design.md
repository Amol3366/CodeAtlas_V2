# Frontend OpenAI credential entry, backed by the Windows Credential Manager

Date: 2026-08-06
Status: approved by the user, not yet planned or implemented
Related: ADR-0011 (`.env` model identity), ADR-0012 (governed answer providers),
ADR-0014 (per-repository embedding model), `AGENTS.md` Sections 4.4, 12.5, 18

## Problem

The OpenAI API key can only be supplied by editing `.env` in the project folder.
A user who wants to enable OpenAI embeddings or OpenAI answer generation must
leave the application, find a file, know the variable name, and restart the
server — while every other provider decision is made in Settings.

The observed report was precise: the embedding options could not be clicked and
OpenAI appeared unavailable. The clicking was an uninstalled optional extra, not
a credential problem, and was fixed by installing it. But the second half of the
request stands on its own: the key should be enterable from the frontend.

`.env` also has a property worth naming, because it is the actual argument for
this change. It is a plaintext file inside a project folder. It gets committed
by accident, copied when a folder is duplicated, opened during screen shares,
and included when someone zips a directory to send it somewhere. A credential
posted to a third party is the one Phase 7 failure that cannot be undone
(`semantic/redaction.py`), and a plaintext file is the most common way it
happens.

Two facts about the current code shape the design:

- **The key is read from `os.environ` in four separate places.**
  `semantic/providers.py:259` (embedding provider construction),
  `semantic/providers.py:399` (availability reporting),
  `generation/openai_provider.py:59` (answer request authorization), and
  `generation/factory.py:90` (answer availability). Four readers means four
  chances for one to miss a new source.
- **`.env` is loaded by mutating the process environment.**
  `load_env_file()` (`settings/env_file.py:124`) writes into `os.environ` for
  every key the real environment has not already set. That is how the key
  currently reaches all four readers.

## Decision

Store the key in the Windows Credential Manager, machine-wide, resolved through
one function, with `.env` retained as a fallback.

The three choices below were confirmed with the user before this document was
written.

### 1. Storage: the Windows Credential Manager

Not the database. `create_backup()` (`storage/sqlite/backup.py:84`) copies the
SQLite file, which is also the artifact a user would attach to a bug report. A
credential stored there travels with every copy of it. Encrypting the column
with DPAPI would make that ciphertext rather than plaintext, which is better but
still ships key material inside the file most likely to be handed to someone
else.

Keeping the secret out of the database entirely makes `AGENTS.md` Section 12.5 —
"provider secrets never appear in GET responses, logs, browser storage, exported
history, or diagnostic bundles" — true by construction for the export and bundle
clauses, rather than true by remembering to redact.

Access is through `ctypes` against `advapi32`: `CredWriteW`, `CredReadW`,
`CredDeleteW`. Target name `CodeAtlas/OPENAI_API_KEY`, type `CRED_TYPE_GENERIC`,
persistence `CRED_PERSIST_LOCAL_MACHINE` so the entry is scoped to the current
user on this machine and does not roam to other machines on a domain profile.

**No new dependency.** `ctypes` is stdlib, which matters because
`documentation/rules.md` forbids adding a dependency without asking.

### 2. Scope: machine-wide

One credential per workstation, which is what `.env` already means. An API key
identifies a billing account, not a repository policy.

The per-repository boundary is not weakened by this, because the credential and
the permission remain separate concerns: `ProviderPolicy.embedding_provider` and
`answer_provider` still decide, per repository, whether any provider may be used
at all. A stored key enables nothing on its own — exactly the property `README.md`
already claims for `.env`.

### 3. Precedence: credential store, then `.env`

The same ladder ADR-0014 established for the embedding model (policy → `.env` →
default), so there is one precedence rule in the codebase rather than two that
disagree. What the user last set in the UI is what runs.

`.env` is retained rather than replaced. Removing it would break scripted and
headless use, and the project-folder rule it obeys — a repository you index must
never configure the tool indexing it — is a Section 4.4 control that this change
has no reason to touch.

## Architecture

### `CredentialStore`

New module `src/codeatlas/settings/credentials.py`. A narrow interface, per
Section 4.5's rule that storage and platform services are reached through
substitutable boundaries:

```text
is_available() -> bool
get()          -> str | None
set(value)     -> None
clear()        -> None
```

Two implementations:

- `WindowsCredentialStore` — the `ctypes`/`advapi32` calls above.
- `UnavailableCredentialStore` — every read returns `None`, `is_available()` is
  `False`, and `set()` raises a typed error. Selected on any non-Windows
  platform, or when `advapi32` cannot be loaded.

Windows 11 is the primary supported environment (Section 5), so a non-Windows
run is not a failure state: it degrades to `.env`, and Settings says the store
is unavailable rather than offering a field that cannot work.

### `resolve_openai_api_key()`

One function, in the same module. Returns the credential-store value if present
and non-empty, otherwise the `.env`/environment value, otherwise `None`. All
four current readers call it instead of reading `os.environ` directly.

**The resolved key is never written back into `os.environ`.** This is the one
non-obvious constraint in the design and it needs to survive as a comment at the
choke point.

CodeAtlas invokes Git through an argument-array subprocess adapter, and a child
process inherits its parent's environment. A credential placed in `os.environ`
is therefore handed to every Git invocation for the lifetime of the server, and
to any future subprocess anyone adds. The `.env` path already has this property
because `load_env_file()` mutates the environment — that is a pre-existing
weakness this design must not extend to the new path. Resolution returns a value
to the caller that needs it; it does not publish it process-wide.

### REST surface

Additive, under the Section 12.5 settings-and-providers grouping:

```text
GET    /v1/credentials
PUT    /v1/credentials/openai
DELETE /v1/credentials/openai
```

`GET /v1/credentials` returns status only:

```json
{
  "openai": {
    "configured": true,
    "source": "credential_store",
    "store_available": true
  }
}
```

`source` is `credential_store`, `env`, or `null`. It lets the UI explain why a
key is active — including the case where a `.env` value is shadowing what the
user believes they saved — without revealing any part of it.

**No masking, not even the last four characters.** A key suffix is still key
material, and a GET response body is logged by intermediaries, pasted into bug
reports, and screenshotted. `configured` plus `source` answers every question a
user actually has about their own credential. This is a deliberate rejection of
a common UX convention; Section 12.5 does not carve out an exception for
"only part of" a secret.

`PUT` is write-only: it accepts `{"api_key": "..."}` and returns the same status
shape as `GET`, never an echo of the input. `DELETE` clears the stored entry and
does not touch `.env` — the application must not edit a file the user owns.

Validation is non-empty after trimming, and `max_length=500`. The existing
model-id fields use 200; a key is not a model id and has grown longer across
format changes, so the bound is set once, generously, rather than becoming the
thing that rejects a valid future key. **Format is not validated.** OpenAI key formats have changed more
than once, and a regex that rejects a valid newer key produces a support report
that reads as "the product is broken" while looking correct in tests. The
existing `POST /v1/models/test` already answers the only question that matters,
by using the key.

### Error shape

Failures return the standard envelope with a stable code and no provider text,
following `_failure_code()` (`application/settings.py`), which exists precisely
because a provider's own message can quote what produced it. New codes:

- `CREDENTIAL_STORE_UNAVAILABLE` — no OS credential store on this platform.
- `CREDENTIAL_WRITE_FAILED` — the store rejected the write.

### Frontend

A `type="password"` input in the Settings provider panel, **never populated from
a server response**, with its own Save and Clear actions.

The credential write does not ride on the settings form's Save. A credential is
not a policy, and mixing them means a failed credential write reports as a
failed settings save — the same reasoning that kept the model pull separate from
saving settings, and the same reasoning that removed it when it could not be
made honest.

States rendered: *Not configured*, *Configured (credential store)*,
*Configured (from `.env`)*, and *Credential store unavailable — set
`OPENAI_API_KEY` in `.env`*. The `.env` case names the file, because a user who
just saved a key and sees `.env` as the source needs to know why.

## What this does not do

Stated plainly, because a security feature that overstates itself is worse than
none.

**This does not protect the key from a local attacker.** The Credential Manager
is user-scoped: any code running as that user can read the entry back, including
CodeAtlas, which is the point. Malware running as the user can read it too — as
it could read `.env`, the process environment, or the memory of the running
server.

What it does is remove the key from a plaintext file inside a project folder,
which is how credentials actually leak in practice: committed, copied, zipped,
screen-shared. That is a real and worthwhile reduction, and it is the whole
claim.

**This does not change what transmits.** Provider opt-in per repository is
unchanged, budgets are unchanged, redaction is unchanged. A stored key still
enables nothing by itself.

**This is not a general secret store.** OpenAI is the only credential CodeAtlas
has; Ollama is loopback and needs none. The interface takes a name so a second
credential is possible later, but no second credential is built now.

## Migration and compatibility

No migration. Nothing is stored in SQLite, so `SCHEMA_VERSION` stays at **14**.

`contract_version` stays **`1.1`**: three additive endpoints, no change to any
existing response.

**A backup no longer carries the credential** — it never did, but it also cannot
now that the key has a place to live outside `.env`. Restoring a database onto a
new machine means re-entering the key there. This is correct behavior and a real
change in user expectation, so it is documented in
`docs/operations/backup-and-restore.md` rather than left to be discovered.

## Testing

- **Unit** — `WindowsCredentialStore` round-trip (write, read, clear, read-after-
  clear); `UnavailableCredentialStore` returns `None` and raises on `set`; the
  precedence ladder resolves store over `.env`, falls back to `.env`, and returns
  `None` when neither is present.
- **Contract** — endpoint shapes; `PUT` never echoes the value; `DELETE` is
  idempotent; the existing `test_no_credential_appears_in_any_response`
  (`tests/contract/test_settings_api.py`) is extended to cover all three new
  routes.
- **Security** — a stored key appears in no response body, no log record, and no
  diagnostics payload; and, asserted explicitly, **is absent from `os.environ`
  after resolution**, which is the subprocess-inheritance constraint stated as a
  test rather than a comment.
- **Component** — the field is `type="password"`, is never populated from a
  server response, and each of the four status states renders.

Windows-only tests are marked so a non-Windows run skips rather than fails,
following the existing `semantic-local` skip convention in
`tests/unit/test_embedding_providers.py`.

## Alternatives

**DPAPI-encrypted column in SQLite.** Simpler, one artifact, and the ciphertext
is undecryptable by another user or machine. Rejected because the database is
the file most likely to be copied to someone else, and putting key material in
it — even encrypted — makes the Section 12.5 export and bundle clauses a matter
of remembering to redact rather than a structural fact.

**DPAPI-encrypted file beside the database.** Keeps the secret out of the
database while staying simple, but adds a second artifact that backup, restore,
deletion, and packaging all have to reason about, and none of them do today.

**Replacing `.env` entirely.** Rejected: it breaks scripted and headless use,
and the project-folder rule is a Section 4.4 control with its own reason to
exist.

**Masking the stored key in `GET`.** Rejected above; a suffix is key material.

**Per-repository credentials.** Rejected as scope: it multiplies stored secrets
and re-entry burden to serve a case — different billing accounts per repository
on one workstation — that no user has asked for.
