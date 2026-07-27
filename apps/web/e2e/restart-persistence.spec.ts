/**
 * Phase 5 gate condition: history survives a backend restart.
 *
 * This was previously proven at the storage layer, which shows the rows are on
 * disk but not that a running browser recovers them. The difference matters:
 * an in-memory cache, a client-side store, or a session-scoped id would all
 * pass a storage test and fail here.
 *
 * The restart is a real process kill, not a reconnect.
 */

import { expect, test } from "./support/fixtures";

test("conversations and messages survive a backend restart", async ({
  page,
  backend,
}) => {
  await page.goto("/");

  await page.getByRole("button", { name: "New chat" }).click();
  await expect(page).toHaveURL(/\/conversations\/conv_/);
  const conversationUrl = page.url();

  // A distinctive title, so the assertion cannot pass on a default one.
  const question = "IdempotencyStore.claim";
  await page.getByLabel("Ask about this repository").fill(question);
  await page.getByRole("button", { name: "Send" }).click();

  await expect(page.getByTestId("message-user")).toContainText(question);
  await expect(page.getByTestId("message-assistant")).toContainText(
    "src/payments/idempotency.py",
  );

  // --- The restart --------------------------------------------------------
  await backend.stop();
  await backend.start();

  // A reload, not a client-side navigation: the page starts from nothing and
  // must recover the thread from the server alone.
  await page.goto(conversationUrl);

  await expect(page.getByTestId("message-user")).toContainText(question);
  await expect(page.getByTestId("message-assistant")).toContainText(
    "src/payments/idempotency.py",
  );

  // The thread is still listed in the sidebar, under the server's own
  // timestamps rather than a client's.
  await expect(
    page.getByRole("button", { name: question.slice(0, 20) }).first(),
  ).toBeVisible();
});
