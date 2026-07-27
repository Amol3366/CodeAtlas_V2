/**
 * The critical workflow, end to end in a browser: add a repository, index it,
 * ask a question, open the evidence behind the answer.
 *
 * This is the product's whole claim in one path. Every step is real — a real
 * repository on disk, a real index, a real deterministic answer, and a real
 * excerpt re-read from the snapshot. Nothing here is stubbed, which is the
 * point: the component tests already prove these parts in isolation, and what
 * was missing was proof that they compose in a browser.
 */

import { expect, test } from "./support/fixtures";

test("a repository can be added, indexed, questioned, and cited", async ({
  page,
  seeded,
}) => {
  await page.goto("/");

  // --- Onboard ------------------------------------------------------------
  await page
    .getByLabel("Add local repository")
    .fill(seeded.onboarding_repository_path);
  await page.getByRole("button", { name: "Add", exact: true }).click();

  // The new repository appears in the selector. Two repositories now exist,
  // so selecting the right one is part of the workflow rather than an accident
  // of there being only one.
  // Exact: "Add local repository" also contains "Repository".
  const selector = page.getByLabel("Repository", { exact: true });
  await expect(selector).toBeVisible();
  await selector.selectOption({ label: "fixture-repo-onboarding" });

  // --- Index --------------------------------------------------------------
  await expect(
    page.getByText("This repository has not been indexed yet."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Index now" }).click();

  // Freshness is read from the snapshot the server actually activated.
  await expect(page.getByTestId("freshness")).toHaveText("fresh", {
    timeout: 30_000,
  });

  // --- Ask ----------------------------------------------------------------
  await page.getByRole("button", { name: "New chat" }).click();
  await expect(page).toHaveURL(/\/conversations\/conv_/);

  await page.getByLabel("Ask about this repository").fill("PaymentService.capture");
  await page.getByRole("button", { name: "Send" }).click();

  const assistant = page.getByTestId("message-assistant");
  await expect(assistant).toContainText("src/payments/service.py");

  // --- Cite ---------------------------------------------------------------
  const citation = page.getByRole("button", {
    name: /^\[1\] src\/payments\/service\.py:/,
  });
  await expect(citation).toBeVisible();
  await citation.click();

  const drawer = page.getByRole("dialog", { name: /^Evidence \[1\]$/ });
  await expect(drawer).toBeVisible();

  // Derivation and confidence are separate facts, and the drawer shows the
  // snapshot the answer used rather than whatever is current.
  await expect(drawer.getByTestId("derivation")).toHaveText("deterministic");
  await expect(drawer.getByTestId("evidence-snapshot")).toContainText("snap_");

  // The excerpt is the real source, re-read and hash-verified by the backend.
  await expect(drawer.getByTestId("excerpt")).toContainText("def capture");

  // Escape closes the drawer and returns focus to the citation that opened it,
  // so a keyboard user is never stranded.
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(citation).toBeFocused();
});
