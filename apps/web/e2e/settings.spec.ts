/**
 * The settings page against a real backend.
 *
 * The component tests stub `fetch`, so they prove the page renders what the
 * server is *assumed* to send. This proves it renders what the server actually
 * sends — the provider list, the availability of each, the budget, and the
 * coverage numbers all come from a running API over a real SQLite database.
 *
 * **Why the transmitting test loads the URL instead of clicking.** Chromium
 * (Playwright 1.62.0) kills its renderer when a *client-side* navigation mounts
 * the transmitting branch of this page. Eight single-variable probes isolated
 * it: the identical React tree renders correctly on a full page load on both
 * engines, and only the client-side path dies. Repository identity and
 * repository switching were both exonerated — moving the policy onto the
 * default repository with no switch anywhere still crashed, and turning the
 * policy off stopped it. It is the same class as the conversation-route defect
 * in `e2e/support/chromium-crash.ts`, on a second route.
 *
 * A full page load keeps the assertion running on both engines rather than
 * skipping Chromium, which is why it is preferred here to a skip.
 *
 * No provider is ever constructed and nothing leaves the machine: the
 * transmitting policy is a stored row, and its extra is not installed.
 */

import type { Page } from "@playwright/test";

import { expect, test } from "./support/fixtures";

interface RepositorySummary {
  readonly repository_id: string;
  readonly display_name: string;
}

/**
 * The repository a fresh load of `/settings` will show.
 *
 * The shell defaults to the first repository the API lists, and which one that
 * is depends on what has already run: the onboarding suite registers a
 * repository whose name sorts first, and it is skipped on Chromium. Asking the
 * server is what makes this test independent of both.
 */
async function defaultRepository(page: Page): Promise<RepositorySummary> {
  const response = await page.request.get("/v1/repositories");
  expect(response.ok()).toBeTruthy();
  const repositories = (await response.json()) as RepositorySummary[];
  expect(repositories.length).toBeGreaterThan(0);
  return repositories[0]!;
}

async function setPolicy(
  page: Page,
  repositoryId: string,
  body: Record<string, unknown>,
): Promise<void> {
  const response = await page.request.patch(
    `/v1/settings?repository_id=${encodeURIComponent(repositoryId)}`,
    { data: body },
  );
  expect(response.ok()).toBeTruthy();
}

test("a repository with no provider says so, and can be saved and tested", async ({
  page,
}) => {
  await page.goto("/");

  // Chosen explicitly rather than taken as the default: the suites share one
  // database and the onboarding suite registers a repository whose name sorts
  // first, so "whatever is selected" would depend on execution order.
  // Exact: "Add local repository" also contains "Repository".
  const selector = page.getByLabel("Repository", { exact: true });
  await expect(selector).toBeVisible();
  await selector.selectOption({ label: "payments-fixture" });

  await page.getByRole("link", { name: "Settings" }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await expect(page.getByTestId("settings-repository")).toHaveText(
    "payments-fixture",
  );

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
  const repository = await defaultRepository(page);
  await setPolicy(page, repository.repository_id, {
    embedding_provider: "openai",
    monthly_token_budget: 1000,
  });

  try {
    await page.goto("/settings");
    await expect(page.getByTestId("settings-repository")).toHaveText(
      repository.display_name,
    );

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

    // The coverage branch a disabled repository can never reach: real counts
    // for a repository that opted in and has embedded nothing.
    await expect(
      page.getByText(/% of this snapshot is embedded/i),
    ).toBeVisible();
  } finally {
    // Restored even on failure. The database outlives this test, and leaving a
    // transmitting policy behind would change what every later test sees.
    await setPolicy(page, repository.repository_id, {
      embedding_provider: "none",
      monthly_token_budget: null,
    });
  }
});
