# A first-class Preflight screen

Status: approved design, not yet implemented
Date: 2026-08-07
Authority: `AGENTS.md` is the contract. This spec is subordinate to it.
Related: ADR-0005 (change assurance), ADR-0006 (web application design),
ADR-0016 (derivation-tiered test edges). Required reading for any UI work:
`documentation/design.md`.

## 1. Why

Change preflight is the product's core wedge — `documentation/PRD.md` calls it
"the product" outright. The web application currently renders it as a section
mounted inside another route, showing a fraction of what the API returns.

`apps/web/src/features/change-analysis/Preflight.tsx` declares a `ChangeReport`
with five fields: `analysis_id`, `status`, `overall_risk`, `findings`,
`warnings`, `limitations`. `ChangeAnalysisReport` also carries `changed_files`,
`changed_symbols`, `impact_edges`, `test_gaps`, `test_gap_reasons`, `evidence`,
and the `base`/`target` refs with their freshness. The screen discards all of it.

So the flagship capability is the thinnest screen in the application, and the
work just merged as ADR-0016 — which explains *why* each test gap is a gap — has
nowhere to appear.

This slice makes Preflight a route, renders what the API already sends, and
shows evidence for every claim.

### What this is not

This does not change the evidence contract, add an endpoint, or alter any
analysis behaviour. Every field rendered here is already on the wire. The work
is frontend-only, and that is a deliberate constraint rather than an accident
of scope — see Section 5.

## 2. Scope

**In scope.** A `/preflight` launcher and a `/preflight/:analysisId` report
route; a sidebar entry; working-tree and commit-range analysis; rendering of
findings, changed symbols, changed files, impact edges, test gaps with their
reasons, warnings, limitations, and inline evidence; loading, empty, and error
states; component, accessibility, and end-to-end tests.

**Out of scope, deferred.** Evidence excerpt fetching and any new backend
endpoint (Section 5). Markdown/SARIF export buttons — `GET /v1/change-analysis/
{id}/report` exists, but export is its own slice. Analysis history or listing.
A diff viewer: `documentation/PRD.md` lists "not an IDE" as a non-goal, and
rendering hunks would drift toward one.

**Out of scope, permanently.** Any claim that a symbol is tested or untested.

## 3. Routes

| Path | Purpose |
| --- | --- |
| `/preflight` | Launcher. Choose working tree or a commit range, run it. |
| `/preflight/:analysisId` | A persisted report, loaded by id. |

Running an analysis `POST`s, then navigates to `/preflight/{analysis_id}`.

The id belongs in the URL for the reason `apps/web/src/app/App.tsx:19-21`
already gives for conversations: the URL identifies the thing being viewed, so a
reload or a shared link lands on the same one. It matters more here.
`Preflight.tsx`'s own docstring states that re-opening an analysis never
re-analyses, because a stored analysis is an audit record and running it again
could quietly produce a different answer to the same question. A screen that
loses that record on reload contradicts a property the product claims.

`GET /v1/change-analysis/{analysis_id}` takes no `repository_id` — the analysis
id is sufficient.

### 3.1 Navigation

A fourth `NavLink` in `apps/web/src/app/Shell.tsx`, beside `/`, `/repositories`,
and `/settings`.

It uses ordinary client-side navigation. The Settings link performs a document
navigation, but that exists specifically to defeat a stale Settings bundle
(`documentation/phases.md`, closed 2026-08-05); it is not a pattern to copy.

### 3.2 The embedded component is removed

`apps/web/src/routes/RepositoriesRoute.tsx:18` mounts `<Preflight>` directly.
That mount is removed and replaced with a plain link to `/preflight`, because
Repositories is where a user lands after indexing and is the natural place to
continue from.

Preflight has one home. Two rendering paths for one report would drift.

## 4. File structure

`Preflight.tsx` is 147 lines that fetch, lay out, and render five kinds of
content. It is replaced, not extended:

```
routes/PreflightRoute.tsx           bare /preflight — the launcher
routes/PreflightAnalysisRoute.tsx   /preflight/:analysisId — loads and composes
features/change-analysis/
  PreflightLauncher.tsx    mode toggle, ref inputs, run buttons
  AnalysisSummary.tsx      verdict header: risk, base/target, freshness, counts
  FindingsList.tsx         findings grouped by severity
  ChangedSymbols.tsx       changed symbols, and changed files without symbols
  ImpactList.tsx           impact edges, each with its derivation
  TestGaps.tsx             gaps, their GapReason, and the disclaimer
  EvidenceRef.tsx          one inline evidence line — shared
  useAnalysis.ts           the two mutations and the report query
```

Each file has one purpose, receives props, and is testable alone. Data fetching
stays in `features/*/` hooks over TanStack Query, never in `components/`, per
`documentation/architecture.md`.

## 5. Evidence is rendered inline, without excerpts

`EvidenceRef` renders `file_path`, `start_line`–`end_line`, `symbol`, `side`,
`derivation`, and `confidence`. Every one of those is already in
`ChangeEvidenceItem`. There is no fetch and no excerpt.

### 5.1 Why the existing evidence drawer cannot be reused

`apps/web/src/features/evidence/EvidenceDrawer.tsx` fetches
`GET /v1/evidence/{id}`, which — per `src/codeatlas/api/routers/entities.py:18`
— "re-verifies a **stored** evidence region against the file on disk". That is
snapshot-scoped evidence from the `EvidenceStore`.

Change-analysis evidence is deliberately different.
`src/codeatlas/contracts.py:460-467` states it directly: `ChangeEvidenceItem`
carries a `side` rather than a `snapshot_id` because "the base side of a working
tree has no stored snapshot, only a commit, and pretending otherwise would hide
the historical nature of base-side citations."

So the two are different ID spaces with different verification semantics.
Routing analysis evidence through the drawer would either fail to resolve or,
worse, resolve to something else. Forcing a `snapshot_id` onto a base-side
citation would erase precisely the distinction the contract protects.

### 5.2 Base-side evidence is labelled historical

A base-side reference is read from a Git commit. It cannot be re-verified
against the working tree, and it is not stale — it is historical, which is a
different thing. The UI labels the side rather than implying either.

### 5.3 Excerpts are deferred deliberately

Showing excerpts would need a new endpoint serving target-side content from disk
and base-side content from a Git blob, with its own validation and staleness
contract. That is a backend design decision with an evidence-contract dimension,
not a rendering detail, and it does not belong in a frontend slice.

Location without an excerpt is honest and complete about *where* the evidence
is. The user opens the file.

## 6. Types come from the generator

`Preflight.tsx:19-36` hand-writes `Finding` and `ChangeReport` interfaces that
duplicate the contract. The new components import from
`apps/web/src/lib/api-types.gen.ts`, which was regenerated during the ADR-0016
slice and therefore already carries `GapReason`, `GapReasonCode`, and
`test_gap_reasons`.

Hand-written duplicates are how a frontend drifts from the contract it consumes:
nothing fails when the backend adds a field, and nothing fails when it removes
one. `documentation/rules.md` forbids hand-editing generated types; hand-writing
parallel ones defeats the same guarantee by another route.

TypeScript strict mode. No `any`.

## 7. The report, top to bottom

Ordered verdict-first, matching `documentation/PRD.md`'s "ordered by risk. This
is the product." A developer whose change is fine reads the header and stops.

### 7.1 Verdict header — `AnalysisSummary`

Overall risk as a **word plus an icon**; the base and target refs with commit and
freshness; counts of changed files, changed symbols, findings, and gaps.

Colour never carries meaning alone (`documentation/design.md`). Freshness is
shown because a stale base means the analysis describes a repository that has
since moved, and hiding that would make a confident report out of an outdated
one.

### 7.2 Findings — `FindingsList`

Grouped by severity in the order critical, high, medium, low, info. Each finding
shows title, code, description, **derivation and confidence as separate fields**,
remediation and limitations when present, and an `EvidenceRef` per evidence id.

A high confidence score never implies a stronger derivation. They are separate
facts and are displayed as separate facts.

Empty state, kept verbatim from the current screen because the wording is
already right: "No findings. That is not a claim that the change is safe — only
that no rule matched it."

### 7.3 What changed — `ChangedSymbols`

Changed symbols with qualified name, kind, change kind, file path, and line
range. Changed files are listed in the same section where a file produced no
symbol-level detail — a deleted configuration file is a real change with no
symbol to attach to, and omitting it would under-report the diff.

### 7.4 What it reaches — `ImpactList`

Impact edges as `source → KIND → target`, each showing its **derivation**.

This is where ADR-0016 becomes visible. A fixture-mediated `TESTS` edge appears
here carrying `low_confidence_heuristic`, so "a test you should probably run"
can never read as "a test that covers this". Rendering an impact edge without
its derivation would undo the distinction that slice was built to create.

### 7.5 Possible test gaps — `TestGaps`

Each entry pairs a `test_gaps` name with its `GapReason`: the reason code, the
human explanation, and an `EvidenceRef` for each backing evidence id.
`NO_TEST_FILE_REFERENCE` carries no evidence, and none is fabricated for it.

The disclaimer is **mandatory, always visible, and not collapsible**, carrying
the meaning already fixed in `src/codeatlas/delivery/markdown_report.py:167`: a
missing `TESTS` edge does not prove absence of coverage, and CodeAtlas does not
execute tests.

The section header says "Possible test gaps". Not "Untested".

### 7.6 Warnings and limitations

Both rendered, neither hidden. Known warning codes render as plain-language
notes, following the 2026-08-04 precedent for `EVIDENCE_EXCERPT_TRUNCATED` and
`LEXICAL_QUERY_RELAXED`; an unrecognised code renders as itself rather than
being dropped.

`documentation/design.md` requires the UI to expose uncertainty rather than hide
it. Limitations are the part that keeps the rest honest.

## 8. The launcher — `PreflightLauncher`

Two modes.

**Working tree** compares the tree against a base ref, default `HEAD`. One
button. This is the common case and needs no configuration.

**Commit range** takes a base and a target ref, defaulting to `HEAD~1` and
`HEAD`. Both are free-text: a ref is anything Git resolves, and a dropdown
cannot enumerate that.

Both require a selected repository; the run control is disabled without one and
says why. Refs are sent as typed and validated by the backend — the frontend
does not attempt to pre-validate Git syntax it does not own.

## 9. States

Every interactive state is handled before the change is done, per
`documentation/design.md`.

| State | Behaviour |
| --- | --- |
| No repository selected | Run disabled, with the reason stated. |
| Running | `Skeleton` for genuinely pending data only. Never fake progress. |
| Empty findings | The verbatim wording in Section 7.2. |
| Clean tree | "No files differ between the two states." Not an error. |
| Not a Git repository | The backend's `CHANGE_ANALYSIS_REQUIRES_GIT` message via `ErrorNotice`. |
| Unresolvable ref | `GIT_REF_UNRESOLVABLE` via `ErrorNotice`; the entered refs are preserved so the user can correct a typo rather than retype both. |
| Unknown `analysisId` | A not-found message with a link back to `/preflight`. |
| Request failed | `ErrorNotice`, with retry. |

Errors surface the backend's standard envelope. Stack traces and filesystem
paths never reach the client.

### 9.1 Do not offer retry for a non-Git repository

`ChangeAnalysisRequiresGitError` is declared `retryable = True`
(`src/codeatlas/domain/errors.py:155`). That looks wrong for this condition —
a directory does not become a Git repository by asking twice — and a retry
button driven off the envelope's `retryable` flag would offer an action that can
only fail again.

This spec does not change the backend flag; that is a separate decision with its
own blast radius. The screen suppresses the retry affordance for this specific
code and instead states what would fix it: the directory is not a Git
repository. The discrepancy is recorded in `documentation/memory.md` as a
follow-up rather than silently worked around.

## 10. Accessibility and responsiveness

WCAG 2.2 AA is a release requirement, not a polish pass. Sections are landmarks
with headings; the severity grouping is a real heading hierarchy, not styled
text; focus-visible rings are the global ones and are not removed locally.

Prose respects `--measure`. **Structured content may exceed it** — a
change-analysis table squeezed into a paragraph column is unreadable, and
`documentation/design.md` allows the exception explicitly. Wide tables scroll
inside their own container; the page never scrolls horizontally.

Mobile collapses sections to a single column. No behaviour is desktop-only.

## 11. Testing

**Component (Vitest + Testing Library).** One suite per component. Two of them
guard the product's honesty rather than its layout, and must not be deleted or
weakened:

- every impact edge renders its derivation;
- the test-gap disclaimer renders whenever any gap is shown.

Also: risk renders as a word and not only a colour; findings show derivation and
confidence separately; `NO_TEST_FILE_REFERENCE` renders no evidence reference;
base-side evidence is labelled as such.

**Accessibility.** `vitest-axe` on the composed route with a populated report.

**End-to-end (Playwright).** One spec: index a repository, run a working-tree
preflight, reload the resulting URL, and see the same analysis.

Run it on **Firefox only**. `documentation/phases.md` records five Chromium
skips across four spec files caused by an upstream renderer defect on
client-side navigation, and this route navigates client-side after a POST. The
skip is declared in the spec with that reason, not silently omitted — an
undeclared gap is the thing the phase record exists to prevent.

## 12. Definition of done

- `/preflight` and `/preflight/:analysisId` route; sidebar entry; the embedded
  mount removed from `RepositoriesRoute` and replaced with a link.
- Findings, changed symbols, changed files, impact edges, test gaps with
  reasons, warnings, limitations, and inline evidence all render.
- Every impact edge shows its derivation; every finding shows derivation and
  confidence separately.
- The test-gap disclaimer is present and not collapsible.
- Types are imported from `api-types.gen.ts`; no hand-written contract
  interfaces remain in this feature.
- Reloading `/preflight/{id}` shows the same persisted analysis.
- Component, axe, and Firefox Playwright suites pass; the Chromium skip is
  declared with its reason.
- No backend file changes. `contract_version` stays `1.1`; `SCHEMA_VERSION`
  stays 14; no migration.
- `documentation/design.md` updated if any token or component pattern changed.
- `documentation/memory.md` updated and a handoff appended to
  `docs/plans/PLAN.md`.
