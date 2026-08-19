import { test } from "./fixtures";

/**
 * The Chromium renderer crash on client-side navigation to a conversation.
 *
 * Chromium (Playwright 1.62.0) kills its renderer when the app navigates
 * client-side to `/conversations/{id}` after creating a conversation. It is a
 * browser defect, not application code: Firefox completes every one of these
 * flows, no JS error is raised in either a production or a development React
 * build, and at the moment of death the heap is flat at 10 MB after 19 requests
 * and 3 navigations — neither a leak nor a loop. The full isolation table is in
 * the 2026-07-28 handoff in `docs/plans/PLAN.md`.
 *
 * **Why skip and not `test.fail()`.** `test.fail()` was tried first, because an
 * expected failure keeps running and reports loudly the day the browser is
 * fixed. It does not work here: a crashed page also breaks context teardown, so
 * Playwright records an error *outside* the test body that no annotation can
 * absorb. It passed when run alone and failed inside the gate, which is the
 * worst possible property for a release check — so a deterministic skip is used
 * instead, and the Chromium gap is carried in the plan rather than in a flake.
 *
 * These four are skipped on Chromium only. The three transport tests still run
 * on both engines, and Firefox runs all seven — so no assertion is lost, only
 * the engine it is proven on.
 *
 * **To check whether the browser has been fixed:** delete this helper's calls
 * and run `pnpm exec playwright test --project=chromium`.
 */
export function skipChromiumRendererCrash(browserName: string): void {
  test.skip(
    browserName === "chromium",
    "Chromium renderer crash on conversation-route navigation — browser defect, passes on Firefox (see docs/plans/PLAN.md 2026-07-28)",
  );
}

/**
 * The Chromium renderer crash on the transmitting Settings fieldset.
 *
 * A **second, distinct trigger** for the same class of defect, ruled by the user
 * on 2026-08-19 and given its own function rather than reusing the one above.
 * The reason string reaches the test report, and labelling this
 * "conversation-route navigation" would name one thing while showing another —
 * the mistake ADR-0019 exists to record.
 *
 * Chromium (Playwright 1.62.0, `chromium-1234`) kills its renderer while
 * rendering the Settings **Embedding provider** fieldset for a repository whose
 * policy transmits. The trace shows `goto("/settings")` completing and the
 * `settings-repository` assertion passing first, so the page mounts and the
 * header renders before the renderer dies. Firefox renders the identical tree
 * correctly.
 *
 * **This one is not reached by a client-side navigation**, which is what makes
 * it distinct. `docs/operations/end-to-end-tests.md` used to claim a full page
 * load rendered the branch correctly on both engines, and that claim is why this
 * test was written with `page.goto` and left unskipped while its neighbours were
 * skipped. It was measured false on 2026-08-19: five runs, five crashes, from a
 * clean state, in isolation and in the full suite, headed and headless, against
 * a freshly built bundle. Residue and a stale bundle were both ruled out.
 *
 * **Skipping a failing test is normally forbidden** by `documentation/rules.md`.
 * This is an explicit user ruling, taken on the same terms as the seven above:
 * the assertion is not lost, only the engine it is proven on, because Firefox
 * runs it. The full reproduction is the 2026-08-19 handoff in
 * `docs/plans/PLAN.md` and its Deferred Register row.
 *
 * **To check whether the browser has been fixed:** delete this call and run
 * `pnpm exec playwright test settings.spec.ts --project=chromium`.
 */
export function skipChromiumSettingsCrash(browserName: string): void {
  test.skip(
    browserName === "chromium",
    "Chromium renderer crash rendering the transmitting Settings fieldset — browser defect, passes on Firefox (see docs/plans/PLAN.md 2026-08-19)",
  );
}
