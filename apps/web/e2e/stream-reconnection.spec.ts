/**
 * Phase 5 gate condition: a stream reconnects without duplicating or losing
 * events.
 *
 * **What this proves, precisely.** The stream contract as a real browser sees
 * it: frames arrive under their SSE event names, sequences are gapless and
 * monotonic, `?after=` resumes exactly where the client left off, and a
 * conversation with no live run is told to read the persisted message instead
 * of being left waiting.
 *
 * **Since P6-STREAM (ADR-0008) it also proves the UI half.** Submission now
 * returns 202 with a queued run, so a run *is* in flight and `Thread` does open
 * a stream. The three tests at the end of this file are the ones that close
 * Phase 6 gate condition 1: the thread reaches its answer through the stream
 * with no reload, an accepted turn is genuinely still queued when the response
 * arrives, and citations survive a reload because they come from storage rather
 * than from a submission response nobody kept.
 *
 * The events are read through the app's own origin and proxy, so this exercises
 * the same path the UI would use. Notably it asserts frames arrive under their
 * *names*: the client had been listening on `onmessage`, which never fires for
 * a named frame, and no unit test could see it because the fake dispatched
 * everything to `onmessage`.
 */

import { expect, test } from "./support/fixtures";
import { skipChromiumRendererCrash } from "./support/chromium-crash";

interface CapturedEvent {
  readonly type: string;
  readonly lastEventId: string;
  readonly sequence: number;
}

interface Captured {
  readonly events: readonly CapturedEvent[];
  readonly closedReason: string | null;
}

/**
 * Read one conversation's stream in the page until it ends.
 *
 * Runs in the browser so the transport is a real `EventSource` — the thing
 * whose named-event dispatch the client has to get right.
 */
async function readStream(
  page: import("@playwright/test").Page,
  conversationId: string,
  after: number | null,
): Promise<Captured> {
  return page.evaluate(
    async ({ conversationId, after }) => {
      const base = `/v1/conversations/${encodeURIComponent(conversationId)}/stream`;
      const url = after === null ? base : `${base}?after=${after}`;
      const types = [
        "run.accepted",
        "retrieval.started",
        "retrieval.progress",
        "evidence.available",
        "generation.delta",
        "answer.completed",
        "run.warning",
        "run.failed",
        "run.cancelled",
        "heartbeat",
      ];

      return await new Promise<{
        events: { type: string; lastEventId: string; sequence: number }[];
        closedReason: string | null;
      }>((resolve) => {
        const source = new EventSource(url);
        const events: {
          type: string;
          lastEventId: string;
          sequence: number;
        }[] = [];
        let closedReason: string | null = null;

        const done = () => {
          source.close();
          resolve({ events, closedReason });
        };

        for (const type of types) {
          source.addEventListener(type, (raw) => {
            const message = raw as MessageEvent<string>;
            const parsed = JSON.parse(message.data) as { sequence: number };
            events.push({
              type: message.type,
              lastEventId: message.lastEventId,
              sequence: parsed.sequence,
            });
            if (
              type === "answer.completed" ||
              type === "run.failed" ||
              type === "run.cancelled"
            ) {
              done();
            }
          });
        }

        source.addEventListener("stream.closed", (raw) => {
          const message = raw as MessageEvent<string>;
          closedReason = message.data;
          done();
        });

        source.onerror = () => done();
        // A stream that says nothing at all must not hang the suite.
        setTimeout(done, 15_000);
      });
    },
    { conversationId, after },
  );
}

/** Create a conversation and answer one question, from the page's origin. */
async function askQuestion(
  page: import("@playwright/test").Page,
  repositoryId: string,
): Promise<string> {
  return page.evaluate(async (repositoryId) => {
    const created = await fetch("/v1/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repository_id: repositoryId }),
    });
    const conversation = (await created.json()) as { conversation_id: string };
    await fetch(`/v1/conversations/${conversation.conversation_id}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: "PaymentService.capture" }),
    });
    return conversation.conversation_id;
  }, repositoryId);
}

test("stream events are named, gapless, and resumable", async ({
  page,
  seeded,
}) => {
  await page.goto("/");
  const conversationId = await askQuestion(page, seeded.repository_id);

  // --- The whole run ------------------------------------------------------
  const full = await readStream(page, conversationId, null);
  const sequences = full.events.map((item) => item.sequence);

  expect(sequences.length).toBeGreaterThan(1);
  // Gapless and monotonic from zero. `Last-Event-ID` resume is meaningless
  // otherwise: a gap would be indistinguishable from a dropped event.
  expect(sequences).toEqual(sequences.map((_, index) => index));

  // Named frames, not anonymous ones. A client on `onmessage` alone sees none
  // of these — which is exactly the defect this assertion pins down.
  expect(full.events[0]?.type).toBe("run.accepted");
  expect(full.events.at(-1)?.type).toBe("answer.completed");

  // The SSE id is the sequence, which is what makes resume work at all.
  expect(full.events[0]?.lastEventId).toBe("0");

  // --- Resume from the middle ---------------------------------------------
  const resumeFrom = 2;
  const resumed = await readStream(page, conversationId, resumeFrom);
  const resumedSequences = resumed.events.map((item) => item.sequence);

  // Exactly what was missed: no duplicate of an applied event, no gap.
  expect(resumedSequences).toEqual(
    sequences.filter((sequence) => sequence > resumeFrom),
  );
  expect(resumedSequences).not.toContain(resumeFrom);
  expect(resumed.events.at(-1)?.type).toBe("answer.completed");
});

test("a conversation with no live run is told to read the persisted answer", async ({
  page,
  seeded,
}) => {
  // Silently holding the connection open would leave a client waiting for
  // events that are never coming.
  await page.goto("/");
  const conversationId = await page.evaluate(async (repositoryId) => {
    const created = await fetch("/v1/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repository_id: repositoryId }),
    });
    return ((await created.json()) as { conversation_id: string })
      .conversation_id;
  }, seeded.repository_id);

  const captured = await readStream(page, conversationId, null);

  expect(captured.events).toHaveLength(0);
  expect(captured.closedReason).toContain("fetch_final_message");
});


/**
 * Gate condition 1, in a browser.
 *
 * Each of these was impossible before P6-STREAM: with the run executing inside
 * the request there was no in-flight state to observe, no stream for the thread
 * to open, and the citations lived in component state that a reload discarded.
 */
test("an accepted turn is still queued when the response arrives", async ({
  page,
  seeded,
}) => {
  await page.goto("/");

  const accepted = await page.evaluate(async (repositoryId) => {
    const created = await fetch("/v1/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repository_id: repositoryId }),
    });
    const conversation = (await created.json()) as { conversation_id: string };
    const posted = await fetch(
      `/v1/conversations/${conversation.conversation_id}/messages`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: "PaymentService.capture" }),
      },
    );
    return {
      status: posted.status,
      body: (await posted.json()) as { status: string; content: string },
    };
  }, seeded.repository_id);

  // 202 and queued: the acknowledgement, not the answer. If this ever returns
  // 201 with content again, the run is back inside the request and every
  // guarantee below is void.
  expect(accepted.status).toBe(202);
  expect(accepted.body.status).toBe("queued");
  expect(accepted.body.content).toBe("");
});

test("the thread reaches its answer through the stream, with no reload", async ({
  page,
  seeded,
  browserName,
}) => {
  skipChromiumRendererCrash(browserName);
  await page.goto("/");
  await page
    .getByLabel("Repository", { exact: true })
    .selectOption(seeded.repository_id);
  await page.getByRole("button", { name: "New chat" }).click();
  await expect(page).toHaveURL(/\/conversations\/conv_/);

  await page
    .getByLabel("Ask about this repository")
    .fill("PaymentService.capture");
  await page.getByRole("button", { name: "Send" }).click();

  // Nothing here reloads or polls by hand. The answer can only appear because
  // the thread opened the stream, followed the run, and read the persisted
  // message when it terminated.
  await expect(page.getByTestId("message-assistant")).toContainText(
    "src/payments/service.py",
    { timeout: 30_000 },
  );
});

test("citations survive a reload", async ({ page, seeded, browserName }) => {
  skipChromiumRendererCrash(browserName);
  await page.goto("/");
  await page
    .getByLabel("Repository", { exact: true })
    .selectOption(seeded.repository_id);
  await page.getByRole("button", { name: "New chat" }).click();
  await page
    .getByLabel("Ask about this repository")
    .fill("PaymentService.capture");
  await page.getByRole("button", { name: "Send" }).click();

  // Inline since the citation moved to the end of the claim it supports.
  const citation = page.getByRole("button", {
    name: /^Evidence 1: src\/payments\/service\.py/,
  });
  await expect(citation).toBeVisible({ timeout: 30_000 });

  await page.reload();

  // The submission response is long gone. A citation visible here came from
  // `message.evidence` on the refetched thread, which is the whole point of
  // storing it.
  await expect(citation).toBeVisible({ timeout: 30_000 });
});
