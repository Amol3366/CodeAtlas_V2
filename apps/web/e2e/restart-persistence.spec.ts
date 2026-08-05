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
import { skipChromiumRendererCrash } from "./support/chromium-crash";

test("conversations and messages survive a backend restart", async ({
  page,
  backend,
  browserName,
}) => {
  skipChromiumRendererCrash(browserName);
  await page.goto("/");

  await page.getByRole("button", { name: "New chat" }).click();
  await page.waitForURL(/\/conversations\/conv_/);

  // The composer is one element reused across threads, and Thread clears the
  // draft whenever `conversationId` changes. Typing before the new thread has
  // settled gets wiped, leaving Send disabled. An empty message list is the
  // app's own signal that the new conversation is the one on screen.
  await expect(page.getByTestId("message-user")).toHaveCount(0);

  // A distinctive title, so the assertion cannot pass on a default one.
  const question = "IdempotencyStore.claim";
  await page.getByLabel("Ask about this repository").fill(question);
  await page.getByRole("button", { name: "Send" }).click();

  await expect(page.getByTestId("message-user")).toContainText(question);
  await expect(page.getByTestId("message-assistant")).toContainText(
    "src/payments/idempotency.py",
  );

  // Captured here, not at creation. The database is worker-scoped, so `/`
  // redirects into whatever conversation an earlier spec left behind, and the
  // app performs more than one navigation while a new chat opens. Reading the
  // URL only once the answer is on screen makes it the thread we actually
  // used, rather than whichever one the URL happened to hold mid-flight.
  const conversationUrl = page.url();

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
