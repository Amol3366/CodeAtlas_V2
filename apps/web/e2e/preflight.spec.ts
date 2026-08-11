/**
 * The preflight route pair against a real backend.
 *
 * The component tests stub `fetch`, so they prove the screen renders what the
 * server is *assumed* to send. This proves the whole loop: a POST to a running
 * API over a real SQLite database, a client-side navigation to the analysis
 * id, and — the part no component test can show — that reloading that URL
 * resolves the *persisted* report rather than component state.
 *
 * That last assertion is the reason the id is in the URL at all. A stored
 * analysis is an audit record; re-opening it must never re-analyze, because
 * running it again could quietly produce a different answer to the same
 * question.
 *
 * **Skipped on Chromium.** Running a preflight navigates client-side to
 * `/preflight/{id}`, which is the exact shape of the renderer crash documented
 * in `e2e/support/chromium-crash.ts` — a browser defect on a fourth route.
 * Unlike the settings suite, the navigation cannot be replaced by a page load
 * here: the navigation *is* what this test exists to prove. Firefox runs every
 * assertion.
 */

import type { Page } from "@playwright/test";

import { expect, test } from "./support/fixtures";

interface RepositorySummary {
  readonly repository_id: string;
  readonly display_name: string;
}

async function allRepositories(page: Page): Promise<RepositorySummary[]> {
  const response = await page.request.get("/v1/repositories");
  expect(response.ok()).toBeTruthy();
  return (await response.json()) as RepositorySummary[];
}

/**
 * Seed the selection rather than clicking through `/repositories`.
 *
 * The suites share one database and the onboarding suite registers a
 * repository whose name sorts first, so "whatever is selected" would depend on
 * execution order. Asking the server is what makes this test independent of it.
 */
async function selectFixtureRepository(page: Page): Promise<void> {
  const repositories = await allRepositories(page);
  const fixture = repositories.find(
    (candidate) => candidate.display_name === "payments-fixture",
  );
  expect(fixture, 'the seed did not register "payments-fixture"').toBeDefined();
  await page.addInitScript(
    ([key, value]) => window.localStorage.setItem(key!, value!),
    ["codeatlas.activeRepositoryId", fixture!.repository_id],
  );
}

test.describe("change preflight", () => {
  test("runs an analysis and survives a reload of its URL", async ({
    page,
    browserName,
  }) => {
    test.skip(
      browserName === "chromium",
      "Chromium renderer dies on the client-side navigation this test exists to prove — browser defect, all assertions pass on Firefox (see docs/plans/PLAN.md)",
    );

    await selectFixtureRepository(page);
    await page.goto("/preflight");

    await expect(
      page.getByRole("heading", { name: "Change preflight" }),
    ).toBeVisible();

    await page.getByRole("button", { name: "Run preflight" }).click();

    // The analysis id reaches the URL, which is what makes the report
    // shareable and reloadable.
    await page.waitForURL(/\/preflight\/.+/);
    await expect(page.getByTestId("overall-risk")).toBeVisible();

    const analysisUrl = page.url();

    // The reload is the assertion. A screen holding the report in component
    // state would lose it here.
    await page.reload();

    expect(page.url()).toBe(analysisUrl);
    await expect(page.getByTestId("overall-risk")).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "What changed" }),
    ).toBeVisible();
  });

  test("is still there after navigating away and back", async ({
    page,
    browserName,
  }) => {
    test.skip(
      browserName === "chromium",
      "Chromium renderer dies on the client-side navigation this test exists to prove — browser defect, all assertions pass on Firefox (see docs/plans/PLAN.md)",
    );

    await selectFixtureRepository(page);
    await page.goto("/preflight");
    await page.getByRole("button", { name: "Run preflight" }).click();
    await page.waitForURL(/\/preflight\/.+/);
    const analysisUrl = page.url();

    // Leaving the screen is what the report has to survive. The record is
    // persisted server-side either way; what used to be lost was the only
    // pointer to it, so coming back landed on an empty launcher and the
    // analysis looked discarded.
    await page.getByRole("link", { name: "Repositories" }).click();
    await expect(
      page.getByRole("heading", { name: "Change preflight" }),
    ).toBeHidden();

    // Exact: the repositories screen also links to the launcher, as
    // "Run a change preflight".
    await page.getByRole("link", { name: "Preflight", exact: true }).click();

    expect(page.url()).toBe(analysisUrl);
    await expect(page.getByTestId("overall-risk")).toBeVisible();

    // ...and running another one is still one click away.
    await expect(
      page.getByRole("link", { name: "Run a new preflight" }),
    ).toBeVisible();
  });
});
