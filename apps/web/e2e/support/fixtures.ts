/**
 * Playwright fixtures shared by the end-to-end suites.
 *
 * The backend is worker-scoped and automatic. Worker-scoped because seeding and
 * indexing a repository costs about a second, and paying that per test would
 * make the suite slow enough that people stop running it. Automatic because a
 * test that forgets to name the fixture would otherwise load the app against a
 * server that was never started — and then fail on a missing element, which
 * points at the UI rather than at the real cause.
 */

import { test as base, expect } from "@playwright/test";

import { HarnessBackend, seed, type SeedResult } from "./backend";

export interface WorkerFixtures {
  readonly backend: HarnessBackend;
  readonly seeded: SeedResult;
}

/** No test-scoped fixtures: everything here outlives an individual test. */
type NoTestFixtures = Record<never, never>;

export const test = base.extend<NoTestFixtures, WorkerFixtures>({
  seeded: [
    // eslint-disable-next-line no-empty-pattern
    async ({}, use) => {
      await use(seed());
    },
    { scope: "worker" },
  ],

  backend: [
    async ({ seeded }, use) => {
      const backend = new HarnessBackend(seeded.database);
      await backend.start();
      await use(backend);
      await backend.stop();
    },
    { scope: "worker", auto: true },
  ],
});

export { expect };
