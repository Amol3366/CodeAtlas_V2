# Security Policy

CodeAtlas reads repositories it does not trust, so its security posture is the
product, not a wrapper around it. The authority is
[`docs/security/threat-model.md`](docs/security/threat-model.md) — objectives,
assets, six trust boundaries, threats, and the enforcement status of each. This
file is the front door: what is covered, how to report, and what is deliberately
not treated as a vulnerability.

## Which versions this covers

**There are no tagged releases, so there is no version table.** A table of
supported semver lines would be fiction here, and the previous contents of this
file — `5.1.x ✅ / 4.0.x ✅` — were the unedited GitHub template describing
versions that have never existed.

`main` is the only supported line. **Report against a commit SHA**, not a version
number.

Several version stamps *do* appear in the product — `SCHEMA_VERSION`,
`contract_version`, and the parser bundle, chunker and resolver versions. Those
describe data and contract compatibility, and govern when an index is considered
stale. They are not product releases and do not imply a support window.

## What CodeAtlas assumes

These assumptions are what make a given behaviour a bug or not, so they are
stated before the scope lists:

- **Local-first, single user.** The API binds to loopback. `--host` accepts
  loopback addresses only and exits otherwise.
- **Nothing leaves the machine** unless a repository owner has opted a specific
  repository into a specific provider.
- **Repository content is data, never instruction.** Every byte, filename and Git
  field is untrusted, including anything that reads like a command.
- **Repository code is never executed** during indexing — no imports, builds,
  tests, package scripts, hooks, binaries, or generated commands.

## Reporting a vulnerability

**Use GitHub's private vulnerability reporting** on
[Amol3366/CodeAtlas_V2](https://github.com/Amol3366/CodeAtlas_V2) — *Security* →
*Report a vulnerability*. It stays private until a fix exists.

**Please do not open a public issue** for anything exploitable. Ordinary bugs
with no security consequence are welcome as normal issues.

Include, as far as you have it:

- the **commit SHA**, and whether you ran from source or the packaged Windows
  artifact;
- OS and Python version;
- which boundary above you believe is crossed;
- a reproduction — ideally a fixture repository, since "point it at this repo and
  index it" is the shape most of these take.

**What to expect, honestly.** This is a single-maintainer project. There is no
response-time commitment and it would be dishonest to publish one. You will get
an acknowledgement, an assessment against the threat model, and either a fix
carrying a regression test or a written reason for declining. A change to any
trust boundary additionally requires an ADR and explicit approval, so those take
longer than a patch.

## In scope

Anything that crosses a documented trust boundary. Concretely:

- **path traversal** or escape from the approved root, including via symlinks,
  Windows junctions, UNC paths, reserved names, or case-folding tricks;
- **execution of repository code** at any point during indexing or analysis;
- **subprocess argument injection** through Git invocation;
- **SQL or FTS injection** through repository text or user queries;
- **prompt injection** in repository content that reaches a provider as
  instruction rather than data;
- **secret leakage** into a GET response, a log, browser storage, an export, or a
  diagnostic bundle;
- **Markdown or HTML injection** through rendered excerpts, model output, or
  repository links;
- **evidence that points outside the approved root**, at another repository, or
  across snapshots;
- **provider egress without opt-in**, or egress that bypasses redaction, budget,
  or timeout controls.

## Out of scope, by design

These are accepted properties of the current threat model, not oversights. If you
think one of them is wrong, that is worth raising — as an argument about the
model, which is a different conversation from a vulnerability report.

- **The local API has no authentication.** It binds to loopback and assumes a
  single trusted local user, so reaching it from another process on the same
  machine is the documented design. Exposing it to a network would require
  authentication, CSRF/CORS review, a revised threat model, and explicit
  approval — that is a change request, not a finding.
- **Opted-in provider egress.** Sending repository content to a provider the
  owner explicitly enabled for that repository is the feature working.
- **Resource exhaustion from a pathological repository.** Traversal and
  extraction bounds are documented limits; hitting one is a limit being reported,
  not a denial of service.
- **Anything requiring existing write access** to the user's machine, database,
  or configuration. An attacker who can edit the SQLite file or the settings has
  already won by assumption.
- **Findings in the evaluation corpus or fixture repositories.** Those are
  deliberately hostile inputs; that is what they are for.

## How fixes are handled

A security fix ships with a regression test that fails without it — a fix nobody
can prove is a fix is not one. Where a fix changes a trust boundary rather than
enforcing an existing one, it needs an ADR recording the decision and its
rollback implications, and the threat model is updated in the same change.
