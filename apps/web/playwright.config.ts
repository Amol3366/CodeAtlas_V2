import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end configuration.
 *
 * Two deliberate choices:
 *
 * - **One worker, no parallelism.** The suites share one API process on one
 *   port and one SQLite database, and one of them restarts that process. Two
 *   workers would be two tests fighting over the same server.
 * - **`vite preview`, not `vite dev`.** The gate builds the app immediately
 *   before this runs, so testing the dev server would test assets no user will
 *   ever receive. The preview server proxies `/v1` to the harness backend,
 *   which the API is never told about — it stays loopback-bound with no CORS
 *   middleware, exactly as it ships.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env["CI"],
  retries: 0,
  reporter: process.env["CI"] ? "line" : "list",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "retain-on-failure",
    video: "off",
  },
  // Two engines on purpose.
  //
  // Firefox is what currently proves the browser workflows end to end. Chromium
  // is kept because it is what most users run, and dropping it to get a green
  // gate would trade real coverage for a comfortable number — the four
  // conversation-route tests it cannot pass are marked `test.fail()` instead, so
  // the gate stays honest about the gap and tells us the moment Chromium can
  // pass them again. See the 2026-07-28 diagnosis in `docs/plans/PLAN.md`.
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
  ],
  webServer: {
    // `--host 127.0.0.1` is load-bearing. Vite's default binds the name
    // `localhost`, which on Windows resolves to `::1` first, so a readiness
    // probe against 127.0.0.1 never answers and the server looks dead. Naming
    // the address also keeps the preview server loopback-only and explicit.
    command: "pnpm exec vite preview --host 127.0.0.1 --port 4173 --strictPort",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env["CI"],
    timeout: 60_000,
  },
});
