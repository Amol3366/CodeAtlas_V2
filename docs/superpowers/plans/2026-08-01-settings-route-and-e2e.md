# Settings Route and End-to-End Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the CodeAtlas web settings page reachable at `/settings` and prove it works against a real backend in a browser, closing two of the seven items carried past the Phase 7 gate.

**Architecture:** A thin `SettingsRoute` reads the active repository from React context, names it on screen, and renders the existing untouched `SemanticSettings`. A sidebar `NavLink` reaches it. The Playwright harness seeds a third fixture repository whose provider policy is already `openai` + budget — a real supported state that constructs no provider — so a new browser suite can exercise both the disabled and the transmitting rendering without installing any optional extra.

**Tech Stack:** React 18 + TypeScript, react-router-dom 6, TanStack Query 5, Vitest + Testing Library + vitest-axe, Playwright 1.62, Python 3.12 (harness only).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-01-settings-route-and-e2e-design.md`. Branch: `settings-route-and-e2e`.
- Policy authority is `CLAUDE.md`. Repository content is untrusted; no provider is constructed and nothing is transmitted by any change here.
- **Do not modify** `apps/web/src/features/settings/SemanticSettings.tsx`, the settings service, or any REST contract.
- **Do not install** `semantic-local`, `semantic-openai`, `torch`, or `lancedb`. `GET /v1/models` reporting `local` and `openai` as unavailable is the expected environment.
- New fixture repository display name is exactly **`transmitting-fixture`**. `RepositoryStore.list_all` orders by `display_name, repository_id`, and the shell defaults to the first entry; a name sorting after `payments-fixture` is what keeps the three existing suites unaffected.
- Every Playwright test selects its repository explicitly. Suites share one worker and one database, and the onboarding suite registers `fixture-repo-onboarding` mid-run, which sorts before `payments-fixture`.
- Run web commands from `apps/web`. Scripts: `pnpm lint`, `pnpm typecheck`, `pnpm test`, `pnpm exec vite build`, `pnpm exec playwright test`.
- `POST /v1/models/test`'s success branch stays untested — it needs an available provider. Records must say **five** carried items, not four.
- Commit after every task. Conventional-commit subjects, and end each message with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `apps/web/src/routes/SettingsRoute.tsx` | **Create.** Resolve the active repository, name it, handle the no-repository empty state, render `SemanticSettings`. |
| `apps/web/src/routes/SettingsRoute.test.tsx` | **Create.** Empty state, repository naming, form presence, accessibility. |
| `apps/web/src/app/App.tsx` | **Modify.** Register the `settings` child route before the catch-all. |
| `apps/web/src/app/Shell.tsx` | **Modify.** Add the sidebar `NavLink`. |
| `apps/web/src/app/Shell.test.tsx` | **Modify.** Assert the link exists and points at `/settings`. |
| `scripts/e2e_backend.py` | **Modify.** Seed the third repository and set its provider policy. |
| `apps/web/e2e/support/backend.ts` | **Modify.** Two new `SeedResult` fields. |
| `apps/web/e2e/settings.spec.ts` | **Create.** Two browser tests over the real API. |
| `docs/operations/end-to-end-tests.md` | **Modify.** Suite table. |
| `docs/operations/web-application.md` | **Modify.** The `/settings` route. |
| `CLAUDE.md` | **Modify.** Carried items seven → five. |
| `docs/plans/PLAN.md` | **Append** one handoff entry. |

---

### Task 1: `SettingsRoute` component

**Files:**
- Create: `apps/web/src/routes/SettingsRoute.tsx`
- Test: `apps/web/src/routes/SettingsRoute.test.tsx`

**Interfaces:**
- Consumes: `useActiveRepository()` from `apps/web/src/app/context.ts`, returning `{ repositoryId: string | null; setRepositoryId: (id: string | null) => void }`. `useRepositories()` from `apps/web/src/lib/queries.ts`, returning a TanStack query whose `data` is `Repository[]` where `Repository = { repository_id: string; display_name: string; created_at: string }`. `SemanticSettings` from `apps/web/src/features/settings/SemanticSettings.tsx`, props `{ repositoryId: string }`.
- Produces: `export function SettingsRoute(): JSX.Element`, used by Task 2. Renders `data-testid="settings-repository"` carrying the active repository's display name.

- [ ] **Step 1: Write the failing test**

Create `apps/web/src/routes/SettingsRoute.test.tsx`:

```tsx
import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import { ActiveRepositoryContext } from "../app/context";
import { renderWithProviders, stubFetch } from "../test/harness";
import { SettingsRoute } from "./SettingsRoute";

/**
 * The route wrapper, not the settings form.
 *
 * Its whole job is to answer "which repository am I about to configure?" —
 * including when the answer is "none yet". This is the one screen that can send
 * repository content off the machine, so a page that silently configured
 * whichever repository context happened to hold would be the wrong default.
 */

const MODELS = {
  models: [
    {
      provider: "none",
      model_id: null,
      dimensions: null,
      available: true,
      transmits_off_machine: false,
      requires: null,
    },
    {
      provider: "local",
      model_id: "sentence-transformers/all-MiniLM-L6-v2",
      dimensions: 384,
      available: true,
      transmits_off_machine: false,
      requires: null,
    },
    {
      provider: "openai",
      model_id: "text-embedding-3-small",
      dimensions: 1536,
      available: false,
      transmits_off_machine: true,
      requires: "extra:semantic-openai and OPENAI_API_KEY",
    },
  ],
};

function stubBackend() {
  return stubFetch({
    "/v1/repositories": {
      body: [
        {
          repository_id: "repo_1",
          display_name: "demo",
          created_at: "2026-07-27T12:00:00Z",
        },
      ],
    },
    "/v1/models": { body: MODELS },
    "/v1/settings?repository_id=repo_1": {
      body: {
        repository_id: "repo_1",
        embedding_provider: "none",
        monthly_token_budget: null,
        per_run_token_budget: null,
        transmits_off_machine: false,
        updated_at: "2026-07-30T12:00:00Z",
      },
    },
    "/v1/repositories/repo_1/semantic-status": {
      body: {
        repository_id: "repo_1",
        provider: "none",
        enabled: false,
        snapshot_id: "snap_1",
        coverage: null,
        total_count: null,
        embedded_count: null,
        pending_count: null,
        failed_count: null,
        namespace_id: null,
        model_id: null,
        is_complete: true,
      },
    },
  });
}

function renderAt(repositoryId: string | null) {
  return renderWithProviders(
    <ActiveRepositoryContext.Provider
      value={{ repositoryId, setRepositoryId: () => undefined }}
    >
      <SettingsRoute />
    </ActiveRepositoryContext.Provider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SettingsRoute", () => {
  it("sends a user with no active repository somewhere they can pick one", async () => {
    // An empty state that states a precondition without saying how to satisfy
    // it is a dead end.
    stubBackend();
    renderAt(null);

    expect(
      await screen.findByText(/select a repository/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /home page/i })).toHaveAttribute(
      "href",
      "/",
    );
  });

  it("names the repository it is about to configure", async () => {
    stubBackend();
    renderAt("repo_1");

    expect(await screen.findByTestId("settings-repository")).toHaveTextContent(
      "demo",
    );
  });

  it("renders the provider form for that repository", async () => {
    stubBackend();
    renderAt("repo_1");

    expect(
      await screen.findByText(/semantic search is optional/i),
    ).toBeInTheDocument();
  });

  it("falls back to the id when the repository list has not arrived", async () => {
    // The name is a nicety; the identity is not. Rendering nothing while the
    // list loads would leave the page unable to say what it configures.
    stubFetch({
      "/v1/models": { body: MODELS },
      "/v1/settings?repository_id=repo_1": {
        body: {
          repository_id: "repo_1",
          embedding_provider: "none",
          monthly_token_budget: null,
          per_run_token_budget: null,
          transmits_off_machine: false,
          updated_at: "2026-07-30T12:00:00Z",
        },
      },
      "/v1/repositories/repo_1/semantic-status": {
        body: {
          repository_id: "repo_1",
          provider: "none",
          enabled: false,
          snapshot_id: "snap_1",
          coverage: null,
          total_count: null,
          embedded_count: null,
          pending_count: null,
          failed_count: null,
          namespace_id: null,
          model_id: null,
          is_complete: true,
        },
      },
    });
    renderAt("repo_1");

    expect(await screen.findByTestId("settings-repository")).toHaveTextContent(
      "repo_1",
    );
  });

  it("has no accessibility violations", async () => {
    stubBackend();
    const { container } = renderAt("repo_1");
    await screen.findByText(/semantic search is optional/i);

    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/web && pnpm exec vitest run src/routes/SettingsRoute.test.tsx`
Expected: FAIL — `Failed to resolve import "./SettingsRoute"`.

- [ ] **Step 3: Write the implementation**

Create `apps/web/src/routes/SettingsRoute.tsx`:

```tsx
import { Link } from "react-router-dom";

import { useActiveRepository } from "../app/context";
import { SemanticSettings } from "../features/settings/SemanticSettings";
import { useRepositories } from "../lib/queries";

/**
 * The settings route.
 *
 * Deliberately thin: `SemanticSettings` owns the provider choice and its
 * disclosure, and this wrapper owns only the question that component cannot
 * answer for itself — *which repository is this?* Context carries an id, so the
 * display name is looked up from the repository list the shell has already
 * fetched.
 *
 * Naming the repository is a requirement rather than a nicety. This is the one
 * screen in CodeAtlas that can cause repository content to leave the machine,
 * and a page that configured whichever repository context happened to hold,
 * without saying which, would make that consequence ambiguous.
 *
 * The repository selector is not duplicated here. It lives in `RepositoryPanel`
 * on the home route, and a second one would be a second place the active
 * repository can change.
 */
export function SettingsRoute() {
  const { repositoryId } = useActiveRepository();
  const repositories = useRepositories();

  if (repositoryId === null) {
    return (
      <div className="mx-auto max-w-[var(--measure)] p-[var(--space-8)]">
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="mt-[var(--space-3)] text-sm text-text-muted">
          Select a repository on the{" "}
          <Link to="/" className="underline">
            home page
          </Link>{" "}
          to configure it.
        </p>
      </div>
    );
  }

  // The id, not a placeholder, while the list is in flight: the name is a
  // nicety and the identity is not.
  const displayName =
    repositories.data?.find((item) => item.repository_id === repositoryId)
      ?.display_name ?? repositoryId;

  return (
    <div className="mx-auto max-w-[var(--measure)] p-[var(--space-8)]">
      <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
      <p className="mt-[var(--space-1)] text-sm text-text-muted">
        Configuring{" "}
        <span data-testid="settings-repository" className="font-medium">
          {displayName}
        </span>
      </p>
      <div className="mt-[var(--space-6)]">
        <SemanticSettings repositoryId={repositoryId} />
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd apps/web && pnpm exec vitest run src/routes/SettingsRoute.test.tsx`
Expected: PASS, 5 tests.

- [ ] **Step 5: Run lint and types**

Run: `cd apps/web && pnpm lint && pnpm typecheck`
Expected: both exit 0.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/routes/SettingsRoute.tsx apps/web/src/routes/SettingsRoute.test.tsx
git commit -m "$(cat <<'EOF'
feat: a settings route that says which repository it configures

The settings form has existed and been tested since P7-08 without anything
rendering it. This is the wrapper it was missing: it resolves the active
repository, names it on screen, and sends a user with no repository selected
back to the page where that choice is made.

Naming the repository is not decoration. This is the one screen that can cause
repository content to leave the machine.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Route registration and sidebar link

**Files:**
- Modify: `apps/web/src/app/App.tsx:11-23`
- Modify: `apps/web/src/app/Shell.tsx:42-47`
- Test: `apps/web/src/app/Shell.test.tsx`

**Interfaces:**
- Consumes: `SettingsRoute` from Task 1.
- Produces: the URL path `/settings`, and a sidebar link with accessible name `Settings`. Task 4's browser suite navigates by clicking that link.

- [ ] **Step 1: Write the failing test**

Append this test inside the existing `describe("Shell", ...)` block in `apps/web/src/app/Shell.test.tsx`, after the `"offers a keyboard-reachable disclosure…"` test:

```tsx
  it("offers a link to settings from the sidebar", async () => {
    // Section 14.1 puts settings in the left sidebar. It sits in the header row
    // rather than the conversation list, because that list is wrapped in a
    // navigation landmark named "Conversations" and a settings link inside it
    // would misdescribe the landmark.
    stubBackend();

    renderWithProviders(
      <ThemeProvider>
        <Shell />
      </ThemeProvider>,
    );

    const link = await screen.findByRole("link", { name: "Settings" });
    expect(link).toHaveAttribute("href", "/settings");
  });
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/web && pnpm exec vitest run src/app/Shell.test.tsx`
Expected: FAIL — `Unable to find an accessible element with the role "link" and name "Settings"`.

- [ ] **Step 3: Add the link to the shell**

In `apps/web/src/app/Shell.tsx`, add `NavLink` to the router import:

```tsx
import { NavLink, Outlet } from "react-router-dom";
```

Then replace the sidebar header block (currently the `<div className="flex items-center justify-between p-[var(--space-3)]">` containing the wordmark and `<ThemeToggle />`) with:

```tsx
            <div className="flex items-center justify-between p-[var(--space-3)]">
              <span className="text-sm font-semibold tracking-tight">
                CodeAtlas
              </span>
              <div className="flex items-center gap-[var(--space-2)]">
                {/* `NavLink` rather than `Link`: it sets aria-current="page" on
                    the active route, the same way the conversation list marks
                    the active thread. */}
                <NavLink
                  to="/settings"
                  className="rounded-[var(--radius-sm)] px-[var(--space-2)] py-[var(--space-1)] text-xs text-text-muted hover:bg-surface-sunken aria-[current=page]:bg-surface-sunken aria-[current=page]:font-medium"
                >
                  Settings
                </NavLink>
                <ThemeToggle />
              </div>
            </div>
```

- [ ] **Step 4: Register the route**

In `apps/web/src/app/App.tsx`, add the import:

```tsx
import { SettingsRoute } from "../routes/SettingsRoute";
```

and add the route as a child of `Shell`, immediately before the `path: "*"` entry:

```tsx
      { path: "settings", element: <SettingsRoute /> },
```

The catch-all must stay last, or it will swallow `/settings`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd apps/web && pnpm test`
Expected: PASS — the whole component suite, including the new Shell test and Task 1's five.

- [ ] **Step 6: Run lint, types, and the build**

Run: `cd apps/web && pnpm lint && pnpm typecheck && pnpm exec vite build`
Expected: all exit 0. The build is required because Task 4's suites serve `dist`, not the dev server.

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/app/App.tsx apps/web/src/app/Shell.tsx apps/web/src/app/Shell.test.tsx
git commit -m "$(cat <<'EOF'
feat: reach the settings page from the sidebar

The route goes before the catch-all, which would otherwise redirect /settings
to the home page. The link sits in the sidebar header beside the theme control,
not in the conversation list — that list is a navigation landmark named
"Conversations", and a settings link inside it would misdescribe it.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Seed a repository whose policy transmits

**Files:**
- Modify: `scripts/e2e_backend.py:107-146` (the `seed` function and its imports)
- Modify: `apps/web/e2e/support/backend.ts:29-37` (the `SeedResult` interface)

**Interfaces:**
- Consumes: `RegisterRepositoryRequest(path: str, display_name: str)`, `services.indexing.index(repository_id) -> IndexResult`, `services.settings.update(repository_id, *, embedding_provider: EmbeddingProviderKind, monthly_token_budget: int)`.
- Produces: two new keys in the seed's JSON output and in `SeedResult` — `transmitting_repository_id: string` and `transmitting_repository_path: string`. Task 4 reads them.

- [ ] **Step 1: Add the import and the fixture path**

In `scripts/e2e_backend.py`, add to the imports:

```python
from codeatlas.domain.semantic import EmbeddingProviderKind
```

- [ ] **Step 2: Extend the seed function**

In `seed`, immediately after the `onboarding_root` assignment, add:

```python
    # A third repository whose provider policy already transmits. Nothing is
    # sent and no provider is constructed — the policy is a row, and setting one
    # for a provider whose extra is absent is a state a user can genuinely reach
    # (embedding then reports SEMANTIC_PROVIDER_UNAVAILABLE and deterministic
    # retrieval is unaffected). It exists so the settings suite can exercise the
    # transmitting disclosure without adding a gigabyte of torch to the gate.
    #
    # The display name is load-bearing: repositories list by display_name and
    # the shell defaults to the first, so a name sorting after
    # "payments-fixture" leaves every existing suite's default unchanged.
    transmitting_root = workdir / "fixture-repo-transmitting"
```

and beside the two existing `if not ....exists()` guards:

```python
    if not transmitting_root.exists():
        _write_fixture_repository(transmitting_root)
```

Inside the `with connect(database) as connection:` block, after the existing
`result = services.indexing.index(repository.repository_id)` line:

```python
        transmitting = services.registration.register(
            RegisterRepositoryRequest(
                path=str(transmitting_root), display_name="transmitting-fixture"
            )
        )
        # Indexed before the policy is set, so the snapshot exists and coverage
        # is a real fraction of real chunks rather than an empty answer.
        services.indexing.index(transmitting.repository_id)
        services.settings.update(
            transmitting.repository_id,
            embedding_provider=EmbeddingProviderKind.OPENAI,
            monthly_token_budget=1000,
        )
```

and extend the returned dictionary with:

```python
        "transmitting_repository_id": transmitting.repository_id,
        "transmitting_repository_path": str(transmitting_root),
```

- [ ] **Step 3: Run the seed and verify its output**

Run from the repository root:

```powershell
uv run --frozen python scripts/e2e_backend.py seed --workdir .e2e-tmp
```

Expected: exit 0, and the printed JSON contains `transmitting_repository_id`
(a `repo_` value) and `transmitting_repository_path` ending in
`fixture-repo-transmitting`.

- [ ] **Step 4: Verify the seeded policy is what the API will report**

Run from the repository root, substituting the id printed above:

```powershell
uv run --frozen python -c "
import json, sys
from codeatlas.application.container import build_services
from codeatlas.storage.sqlite.connection import connect
with connect(r'.e2e-tmp/codeatlas.db') as c:
    s = build_services(c)
    repo = [r for r in s.repositories.list_all() if r.display_name == 'transmitting-fixture'][0]
    print(json.dumps({
        'provider': s.settings.get(repo.repository_id).embedding_provider.value,
        'budget': s.settings.get(repo.repository_id).monthly_token_budget,
        'coverage': s.semantic_status.status(repo.repository_id).coverage,
        'total': s.semantic_status.status(repo.repository_id).total_count,
    }))
"
```

Expected: `provider` is `openai`, `budget` is `1000`, `coverage` is `0.0`, and
`total` is greater than 0. If `coverage` were `null` the settings page would
render "nothing to cover" and Task 4's second test could not pass.

- [ ] **Step 5: Update the harness type**

In `apps/web/e2e/support/backend.ts`, extend `SeedResult`:

```ts
export interface SeedResult {
  readonly database: string;
  readonly repository_id: string;
  readonly repository_path: string;
  readonly onboarding_repository_path: string;
  readonly transmitting_repository_id: string;
  readonly transmitting_repository_path: string;
  readonly snapshot_id: string;
  readonly file_count: number;
  readonly symbol_count: number;
}
```

- [ ] **Step 6: Confirm the existing suites still pass**

Run: `cd apps/web && pnpm exec playwright test`
Expected: the three existing suites pass on both projects, exactly as before.
This is the check that the new repository did not change any suite's default
active repository.

- [ ] **Step 7: Commit**

```bash
git add scripts/e2e_backend.py apps/web/e2e/support/backend.ts
git commit -m "$(cat <<'EOF'
test: seed a fixture whose provider policy already transmits

The settings page's highest-consequence rendering — the transmit warning, the
budget field, real coverage numbers — is unreachable in an environment with no
extras installed, because the UI disables every provider that is unavailable.

Rather than add a gigabyte of torch to the gate, the harness seeds a repository
whose policy is openai with a budget. That is a state a user can genuinely
reach, it constructs no provider, and it transmits nothing.

The display name sorts after payments-fixture on purpose: repositories list by
display name and the shell defaults to the first.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: The Playwright suite

**Files:**
- Create: `apps/web/e2e/settings.spec.ts`

**Interfaces:**
- Consumes: `test`/`expect` from `./support/fixtures`, the worker-scoped `seeded: SeedResult` fixture from Task 3, the `/settings` route and `Settings` link from Task 2, `data-testid="settings-repository"` from Task 1.
- Produces: nothing other tasks consume.

- [ ] **Step 1: Write the suite**

Create `apps/web/e2e/settings.spec.ts`:

```ts
/**
 * The settings page against a real backend.
 *
 * The component tests stub `fetch`, so they prove the page renders what the
 * server is *assumed* to send. This proves it renders what the server actually
 * sends — the provider list, the availability of each, the budget, and the
 * coverage numbers all come from a running API over a real SQLite database.
 *
 * Both tests select their repository explicitly rather than relying on the
 * default. The suites share one worker and one database, and the onboarding
 * suite registers a repository whose name sorts before this one's — so relying
 * on "the first repository" would make these tests depend on execution order.
 *
 * No provider is ever constructed and nothing leaves the machine: the
 * transmitting repository's policy is a stored row, and its extra is not
 * installed.
 */

import { expect, test } from "./support/fixtures";

/** Choose a repository on the home page, then open its settings. */
async function openSettingsFor(
  page: import("@playwright/test").Page,
  displayName: string,
): Promise<void> {
  await page.goto("/");
  // Exact: "Add local repository" also contains "Repository".
  const selector = page.getByLabel("Repository", { exact: true });
  await expect(selector).toBeVisible();
  await selector.selectOption({ label: displayName });

  await page.getByRole("link", { name: "Settings" }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await expect(page.getByTestId("settings-repository")).toHaveText(displayName);
}

test("a repository with no provider says so, and can be saved and tested", async ({
  page,
}) => {
  await openSettingsFor(page, "payments-fixture");

  // --- The provider list, from the real /v1/models ------------------------
  const providers = page.getByRole("group", { name: "Embedding provider" });
  await expect(providers).toBeVisible();

  // Words, not colour alone (Section 14.4).
  await expect(
    providers.getByText("Sends repository content off this machine"),
  ).toBeVisible();
  await expect(
    providers.getByText("Stays on this machine").first(),
  ).toBeVisible();

  // An unavailable provider explains itself rather than vanishing. The text
  // comes from the server, which knows the extra is absent.
  await expect(
    providers.getByText(/requires extra:semantic-openai/i),
  ).toBeVisible();

  // --- Coverage -----------------------------------------------------------
  // "Not applicable" is a different fact from 0%.
  await expect(page.getByText(/nothing to cover/i)).toBeVisible();

  // --- A real POST /v1/models/test ----------------------------------------
  // The disabled branch: a provider that is off cannot answer, and the page
  // reports the server's code rather than inventing a message.
  await page.getByRole("button", { name: "Test provider" }).click();
  await expect(page.getByText(/PROVIDER_DISABLED/)).toBeVisible();

  // --- A real PATCH /v1/settings ------------------------------------------
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Settings saved.")).toBeVisible();

  // --- Persistence --------------------------------------------------------
  // A reload starts from nothing and must read the policy back from the server.
  await page.reload();
  await expect(page.getByRole("radio", { name: /disabled/i })).toBeChecked();
});

test("a repository whose policy transmits shows the warning, the budget, and its coverage", async ({
  page,
}) => {
  await openSettingsFor(page, "transmitting-fixture");

  // The consequence is stated in words on the selected option.
  await expect(
    page.getByText("Sends repository content off this machine"),
  ).toBeVisible();

  // Selected, and still disabled: the policy was set before the extra was
  // installed, which is a real state and not a contradiction.
  const openai = page.getByRole("radio", { name: /openai/i });
  await expect(openai).toBeChecked();
  await expect(openai).toBeDisabled();

  // The budget the server is holding, not a default the form invented.
  await expect(page.getByLabel(/monthly token budget/i)).toHaveValue("1000");

  // The coverage branch the disabled repository can never reach: real counts
  // for a repository that opted in and has embedded nothing.
  await expect(
    page.getByText(/0% of this snapshot is embedded/i),
  ).toBeVisible();
});
```

- [ ] **Step 2: Run the new suite on Firefox**

Run: `cd apps/web && pnpm exec playwright test settings.spec.ts --project=firefox`
Expected: PASS, 2 tests.

- [ ] **Step 3: Run the new suite on Chromium**

Run: `cd apps/web && pnpm exec playwright test settings.spec.ts --project=chromium`
Expected: PASS, 2 tests.

**If and only if Chromium crashes its renderer here**, add
`import { skipChromiumRendererCrash } from "./support/chromium-crash";`, take
`browserName` in each test's fixture argument, call
`skipChromiumRendererCrash(browserName)` as the first line of each, and record
the observed failure in the Task 5 handoff. Do not add the skip pre-emptively —
the known defect is specific to `/conversations/{id}` navigation, and widening
it without evidence would hide a real regression.

- [ ] **Step 4: Run every suite on both engines**

Run: `cd apps/web && pnpm exec playwright test`
Expected: all suites pass. Firefox runs everything; Chromium skips the four
conversation-route tests it cannot pass, as before.

- [ ] **Step 5: Commit**

```bash
git add apps/web/e2e/settings.spec.ts
git commit -m "$(cat <<'EOF'
test: prove the settings page against a running backend

The component tests stub fetch, so they prove the page renders what the server
is assumed to send. These prove it renders what the server sends: the provider
list and each provider's availability, a real POST /v1/models/test reporting
PROVIDER_DISABLED, a real PATCH that persists across a reload, and — on the
seeded transmitting repository — the warning, the stored budget, and real
coverage numbers.

Both tests pick their repository explicitly. Suites share one database and the
onboarding suite registers one whose name sorts first.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Records and the gate

**Files:**
- Modify: `docs/operations/end-to-end-tests.md`
- Modify: `docs/operations/web-application.md`
- Modify: `CLAUDE.md` (the Phase 7 section's carried-items paragraph)
- Modify: `docs/plans/PLAN.md` (append one handoff entry)

**Interfaces:**
- Consumes: the verification results from Tasks 1–4.
- Produces: nothing code depends on.

- [ ] **Step 1: Document the suite**

In `docs/operations/end-to-end-tests.md`, find the section listing what each
suite proves and add an entry for `settings.spec.ts`, stating that it covers
the settings route against the real API for both a repository with no provider
and one whose stored policy transmits, and that the transmitting case is seeded
rather than selected because no optional extra is installed.

- [ ] **Step 2: Document the route**

In `docs/operations/web-application.md`, add `/settings` to the route list with:
the active repository comes from the shell's context and is named on the page;
with no repository selected the route offers a link back to the home page; the
repository selector is not duplicated onto this route.

- [ ] **Step 3: Correct the carried-item count**

In `CLAUDE.md`, in the Phase 7 section, the sentence beginning "Seven items were
carried into the approval as open work with no later phase to absorb them"
currently lists: the three Phase 6 qualifications, the 1.05 GB packaged semantic
tree, the unrouted web settings page, the untested `POST /v1/models/test`
success branch, and the absent settings Playwright coverage.

Change it to **five**, removing the unrouted settings page and the absent
settings Playwright coverage from the list, and append:

```markdown
Two of the original seven closed on 2026-08-01: the web settings page is routed
at `/settings` and covered by `apps/web/e2e/settings.spec.ts`. The
`POST /v1/models/test` success branch is **not** among them — it needs an
available provider, and no optional extra is installed.
```

Do not touch the gate approval sentence or any evidence list above it.

- [ ] **Step 4: Append the handoff**

Append a new entry at the top of the Handoff Log in `docs/plans/PLAN.md`,
directly below the `## Handoff Log` heading, following the Handoff Schema:
UTC timestamp and agent label; transition (none — Phase 7 stays `complete`, this
is post-gate remediation); outcome and user-visible behavior; files changed;
contracts/migrations (none); the exact verification commands with their exit
codes and summarized results; limitations — explicitly that five carried items
remain and why the `POST /v1/models/test` success branch is not closed; and the
next required decision (none — awaiting user instruction).

Do not modify any existing entry.

- [ ] **Step 5: Run the full gate**

Run from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check_phase7.ps1 -SkipSync
```

Expected: exit 0. Record the actual exit code in the handoff — if it is not 0,
fix the cause and re-run rather than recording a pass.

- [ ] **Step 6: Commit**

```bash
git add docs/operations/end-to-end-tests.md docs/operations/web-application.md CLAUDE.md docs/plans/PLAN.md
git commit -m "$(cat <<'EOF'
docs: two of the seven carried items are closed, five remain

The settings page is routed and covered end to end, so the records that say
seven would now understate what is done. The count goes to five, not four: the
POST /v1/models/test success branch still needs an available provider and no
optional extra is installed.

Phase 7's gate approval text and every prior handoff are untouched. Rewriting
the evidence a gate was approved on is not record-keeping.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**Spec coverage.** Every spec section maps to a task: route and navigation →
Task 2; `SettingsRoute` including the display-name lookup, the empty state with
its link, and the no-duplicate-selector rule → Task 1; harness seeding including
the load-bearing display name → Task 3; the two-test Playwright suite and the
no-pre-emptive-skip rule → Task 4; component tests → Task 1 step 1; records and
verification → Task 5. The spec's acceptance criteria 1–3 are covered by Tasks
1–2 and asserted in Task 4; criterion 4 by Task 4 steps 2–3; criterion 5 by
Task 3 step 6 and Task 4 step 4; criterion 6 by Task 5 step 5; criterion 7 by
Task 5 step 3.

**Placeholder scan.** No TBD/TODO. Every code step carries the literal code.
Task 5's steps describe prose edits to specific named passages rather than
quoting whole documents, which is the intended granularity for documentation.

**Type consistency.** `SettingsRoute` is named identically in Tasks 1, 2, and
its import path. `data-testid="settings-repository"` is produced in Task 1 and
consumed in Task 4's helper. `transmitting_repository_id` and
`transmitting_repository_path` are produced by Task 3 in both the Python dict
and the TypeScript interface with matching snake_case. `EmbeddingProviderKind`
is imported in Task 3 from `codeatlas.domain.semantic`, matching
`application/settings.py`. The display name `transmitting-fixture` is identical
in Task 3 and Task 4.

**One deliberate gap.** Task 3's step 4 verification uses
`services.repositories.list_all()`, which is exposed on `ApplicationServices`
as the `repositories` field (`RepositoryStore`). It is a check command, not
shipped code.
