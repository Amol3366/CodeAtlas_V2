# Settings route and its end-to-end coverage

Date: 2026-08-01
Status: approved by the user 2026-08-01
Policy authority: `CLAUDE.md`
Related: `docs/plans/PLAN.md` (Phase 7 carried items), ADR-0009, ADR-0010

## Problem

Two of the seven items carried past the Phase 7 gate concern the same screen:

1. **The web settings page is unrouted.** `apps/web/src/features/settings/SemanticSettings.tsx`
   exists and has eight component tests, but no route renders it and no
   navigation reaches it. A user cannot choose an embedding provider from the
   browser at all; the only working surfaces are `codeatlas settings` and
   `PATCH /v1/settings`.
2. **There is no Playwright coverage for settings.** The component tests stub
   `fetch`, so nothing proves the page's expectations match what the real server
   sends.

Both are user-visible: the first is a feature that ships dead, the second is the
gap between a page that works against fixtures and a page that works.

This is post-gate cleanup, not resumed phase work. Phase 7's approval text is
evidence and is not rewritten.

## Constraint discovered before design

No semantic extras are installed in the development environment:

```
sentence_transformers  False
lancedb                False
torch                  False
openai                 False
```

`GET /v1/models` therefore reports `local` and `openai` as `available: false`,
and `SemanticSettings` renders their radios `disabled`. **A browser can only
ever select `none` here.** Any design that depends on enabling a provider
through the UI would require adding roughly 1 GB of `torch` to the gate.

`SettingsService.update` does not check availability — it enforces only that a
transmitting provider carries a monthly budget. Setting a policy of `openai`
while the extra is absent is a real, supported state: embedding then reports
`SEMANTIC_PROVIDER_UNAVAILABLE` and deterministic retrieval is unaffected. That
is what makes the seeding approach below possible without installing anything.

## Decisions

| # | Decision | Rejected alternative |
| --- | --- | --- |
| 1 | Route is `/settings`, scoped by the active repository from context | `/repositories/:id/settings` and `/settings?repository=` — both reload-stable, both add a second place repository selection lives |
| 2 | Nav entry sits in the sidebar header beside `ThemeToggle` | Inside the conversation list, which is wrapped in `<nav aria-label="Conversations">` and would misdescribe the landmark |
| 3 | A thin `SettingsRoute` owns the null-repository case; `SemanticSettings` is unchanged | Widening `SemanticSettings`'s props to `string \| null`, which would put empty-state handling inside a component whose job is disclosure |
| 4 | The harness seeds a third repository whose policy is already `openai` + budget | Installing `semantic-local` in the gate; or never exercising the transmitting rendering |
| 5 | The suite runs on both browser engines with no skip helper | Pre-emptively skipping Chromium, which would assume a defect not yet observed on this route |
| 6 | Live records updated, gate evidence untouched | Code-only (records drift); or reopening the Phase 7 board (§20 says the development order is finished) |

## Design

### Route and navigation

`apps/web/src/app/App.tsx` gains one child route under `Shell`:

```
{ path: "settings", element: <SettingsRoute /> }
```

placed before the `*` catch-all, which continues to redirect unknown paths to
`/`.

`apps/web/src/app/Shell.tsx` gains a `NavLink` to `/settings` in the sidebar
header row that currently holds the CodeAtlas wordmark and `ThemeToggle`.
`NavLink` sets `aria-current="page"` on the active route, matching how the
conversation list marks the active thread.

### `SettingsRoute`

New file `apps/web/src/routes/SettingsRoute.tsx`:

- reads `useActiveRepository()` for the id, and `useRepositories()` for the
  matching record — context carries only the id, so the display name is looked
  up from the repository list the shell has already fetched;
- when `repositoryId === null`, renders the §14.2 empty state, which names where
  the choice is made: "Select a repository on the home page to configure it,"
  with a `Link` to `/`. An empty state that states a precondition without
  saying how to satisfy it is a dead end;
- otherwise renders the active repository's **display name** above
  `<SemanticSettings repositoryId={repositoryId} />`.

The repository selector itself is **not** duplicated onto this route. It lives
in `RepositoryPanel` on the home route, and a second selector would be a second
place the active repository can be changed.

Naming the repository is required, not decorative: this is the one screen that
can cause repository content to leave the machine, and a page that silently
configures whichever repository context happens to hold would make that
consequence ambiguous.

Container classes match `HomeRoute` (`mx-auto max-w-[var(--measure)]
p-[var(--space-8)]`) so reading width is consistent across routes.

`SemanticSettings` itself is not modified.

### Harness seeding

`scripts/e2e_backend.py`'s `seed` gains a third fixture repository:

- written to `<workdir>/fixture-repo-transmitting` by the existing
  `_write_fixture_repository` helper;
- registered with display name **`transmitting-fixture`**;
- indexed, so `semantic-status` has an active snapshot with real chunk counts;
- given `embedding_provider=openai, monthly_token_budget=1000` through
  `services.settings.update`.

No provider is constructed and nothing is transmitted. The policy is a row.

**The display name is load-bearing.** `RepositoryStore.list_all` orders by
`display_name, repository_id`, and `Shell` defaults the active repository to the
first entry. `transmitting-fixture` sorts after `payments-fixture`, so the
default active repository is unchanged and the three existing suites are
unaffected.

The seed's JSON output gains `transmitting_repository_id` and
`transmitting_repository_path`; `SeedResult` in `e2e/support/backend.ts` gains
the matching fields.

### Playwright suite

New file `apps/web/e2e/settings.spec.ts`, two tests. Both select their
repository explicitly rather than relying on the default, because the onboarding
suite registers a repository mid-run and suites share one worker and one
database.

**Test 1 — a repository with no provider**

- the sidebar Settings link navigates to `/settings`;
- all three providers are listed, from the real `GET /v1/models`;
- each states in words whether it transmits;
- `openai` shows `requires extra:semantic-openai`;
- coverage reads "No provider is enabled … nothing to cover";
- **Test provider** issues a real `POST /v1/models/test` and reports
  `PROVIDER_DISABLED`;
- **Save** issues a real `PATCH /v1/settings` and reports "Settings saved.";
- a page reload still shows `none`.

**Test 2 — a repository whose policy transmits**

Because the selector lives on the home route, the test switches repositories the
way a user does: `goto("/")`, choose `transmitting-fixture` in the `Repository`
selector, then follow the sidebar Settings link. Then:

- the page renders
  "⚠ Sends repository content off this machine";
- the monthly budget field is visible and holds `1000`;
- coverage renders real numbers from the server (`0% … 0 of N`), which is the
  branch the disabled repository can never reach.

Both engines, no `skipChromiumRendererCrash`. If Chromium turns out to crash on
this route too, the helper is added and the fact is recorded — not assumed in
advance.

### Component tests

`apps/web/src/routes/SettingsRoute.test.tsx` adds:

- renders the empty state when no repository is active;
- renders the settings form and the repository's display name when one is;
- no accessibility violations (`vitest-axe`), matching the existing suites.

## Out of scope

- **`POST /v1/models/test`'s success branch stays untested.** It requires an
  available provider, which requires the extras. Five carried items remain, not
  four; the records must say five.
- No change to `SemanticSettings`, the settings service, or any REST contract.
- No new provider, no extras installed, no transmission.

## Records

| File | Change |
| --- | --- |
| `docs/plans/PLAN.md` | **Append** a handoff entry: what closed, commands run, exit codes |
| `CLAUDE.md` §20 | Carried items seven → five, noting the two closed 2026-08-01 |
| `docs/operations/end-to-end-tests.md` | Suite table gains the settings suite |
| `docs/operations/web-application.md` | The `/settings` route and its empty state |

Phase 7's gate approval text and every prior handoff entry are left exactly as
approved. Rewriting the evidence a gate was approved on is not record-keeping.

## Verification

Run from `apps/web` unless noted, with actual exit codes recorded in the PLAN
handoff:

```powershell
pnpm lint
pnpm typecheck
pnpm test
pnpm exec vite build
pnpm exec playwright test          # chromium and firefox
powershell -ExecutionPolicy Bypass -File scripts/check_phase7.ps1 -SkipSync
```

The gate is the place these are required to pass.

## Amendment — 2026-08-01, approved by the user during implementation

Decision 4 (seed a repository whose policy transmits) and decision 5 (run on both
engines with no skip) collided in practice: **selecting that repository and
navigating client-side to `/settings` kills the Chromium renderer.**

Eight single-variable probes isolated it. The same React tree renders correctly
on a full page load on both engines; only client-side navigation into the
transmitting branch dies. Repository identity and repository switching were both
exonerated — moving the policy onto the default repository with no switch
anywhere still crashed, and turning the seeded repository's policy off stopped
it. It is the conversation-route defect's class, on a second route.

Given the choice between skipping the test on Chromium and reaching the same
rendering by full page load, the user chose the full page load. So:

- **Decision 4 is withdrawn.** No repository is seeded; commit `246edea` was
  reverted by `71008ec`. The transmitting test sets the policy through the real
  API on whichever repository a fresh load will show, and restores it in a
  `finally` block.
- **Decision 5 holds, and cost nothing.** Both tests run on both engines and no
  new skip was added.
- The "Harness seeding" section above is therefore historical. The Playwright
  section's two tests are as built, except that the second reaches the page by
  `page.goto("/settings")` rather than by clicking.

Everything else — the route, the wrapper, the empty state, the naming
requirement, the records, and the five-not-four carried-item count — is as
approved.

## Acceptance criteria

1. `/settings` is reachable from the sidebar in a browser and renders the
   provider form for the active repository.
2. With no repository active, the route renders an empty state rather than a
   blank page or an error.
3. The page names which repository it is configuring.
4. `settings.spec.ts` passes on Chromium and Firefox, exercising real
   `GET /v1/models`, `GET /v1/settings`, `PATCH /v1/settings`,
   `POST /v1/models/test`, and `GET /v1/repositories/{id}/semantic-status`.
5. The three pre-existing Playwright suites still pass unchanged.
6. `check_phase7.ps1 -SkipSync` exits 0.
7. The records say five carried items and name what closed.
