# Release Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Get `check_phase7.ps1` to exit 0 end to end, then run the four release-validation legs and the by-hand install/uninstall step, so the closeout's outstanding verification is either complete or explicitly declared.

**Architecture:** One blocking defect gates everything. `Invoke-Checked` throws on non-zero and the Playwright step sits above the `-Semantic`/`-Package`/`-Perf` blocks, so no leg can run while `restart-persistence` fails. RV-01 is an experiment that confirms or falsifies the seeding hypothesis; RV-02 fixes test isolation only; RV-03 to RV-06 run the legs; RV-07 is the by-hand step; RV-08 records. No product code is touched.

**Tech Stack:** PowerShell 5.1, Python 3.12 + pytest, Playwright 1.62 (Chromium + Firefox), pnpm, PyInstaller, SQLite.

**Spec:** `docs/superpowers/specs/2026-09-03-release-validation-design.md`

## Global Constraints

Copied verbatim from `AGENTS.md` and the closeout record; every task's requirements implicitly include these.

- **No version constant moves in this plan.** `SCHEMA_VERSION` **14**, `contract_version` **1.1**, `PARSER_BUNDLE_VERSION` **1.9.0**, `CHUNKER_VERSION` **1.1.0**, `RESOLVER_VERSION` **1.5.0**, `RETRIEVAL_POLICY_VERSION` **5.4**. **No task here forces a reindex.** If one appears to, stop and raise it.
- **No product behaviour change.** This plan changes test-harness code and documentation only. A fix that requires touching `src/codeatlas/` is a scope change — stop and raise it.
- **DO NOT delete, skip, or weaken a test to make a build pass.** Quarantining `restart-persistence` removes the only browser proof of a Phase 5 gate condition; it needs an explicit user ruling, not an executor's judgement.
- **Do not claim a test passed unless you ran it here.** Record the command, the exit code, and the counts.
- **Never edit a tracked file while a gate run is in flight.** `test_deferred_register.py` reads `docs/plans/PLAN.md` and `test_readme_claims.py` reads `README.md`; editing either mid-run voids that run.
- **`$?` after a pipe is the last stage's exit code.** Capture exit codes without a pipe: `cmd > file 2>&1; echo $?`.
- **Whitespace in a doc-scraping regex is `\s+`, never a literal space** — a claim the prose wraps across a line is otherwise invisible.
- **Lint is `ruff check src tests scripts apps`.** Do NOT run `ruff format`: the repo does not use it and 205 files would reflow.
- **Write captured output through Python with an explicit LF newline.** `>` redirection writes CRLF on Windows and `test_working_tree_line_endings.py` fails on it.
- Append to the `docs/plans/PLAN.md` handoff log; never rewrite it. Update `documentation/memory.md` at the end.

---

## File Structure

**Created:**

| File | Responsibility |
| --- | --- |
| `docs/evaluation/e2e-isolation.md` | The RV-01 experiment: what was run, what it showed, and the mechanism it confirms or kills |

**Modified:**

| File | Change |
| --- | --- |
| `apps/web/e2e/restart-persistence.spec.ts` | Scope assertions to the conversation the test created (RV-02, only if RV-01 confirms) |
| `docs/plans/PLAN.md` | Register row 115 disposition; handoff entry; Active Work |
| `documentation/memory.md` | Resume point |
| `README.md` | Test count, only if RV-02 changes it |

---

### Task RV-01: Establish the mechanism by experiment, before changing anything

The register carried this as an intermittent flake for two weeks. The spec argues it is a deterministic state dependency. **Neither claim is acted on until a command settles it**, because the last three programs each found a premise that died on one command.

**Files:**
- Create: `docs/evaluation/e2e-isolation.md`
- Read only: `apps/web/e2e/support/fixtures.ts`, `apps/web/e2e/support/backend.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: a verdict string used by RV-02 — either `CONFIRMED: cross-project state dependency` or `FALSIFIED: <what actually happens>`.

- [ ] **Step 1: Establish the baseline — the full run must fail**

```bash
cd apps/web
pnpm exec playwright test > /tmp/rv01_full.txt 2>&1; echo "EXIT=$?"
grep -E "passed|failed|skipped" /tmp/rv01_full.txt | tail -3
```

Expected: non-zero exit, `restart-persistence` among the failures. If it PASSES, the defect did not reproduce this session — stop, record that in `e2e-isolation.md`, and raise it: the rest of this plan assumes a reproducible failure.

- [ ] **Step 2: Run the Firefox project alone — the decisive comparison**

```bash
cd apps/web
pnpm exec playwright test --project=firefox > /tmp/rv01_ff.txt 2>&1; echo "EXIT=$?"
grep -E "passed|failed|skipped" /tmp/rv01_ff.txt | tail -3
```

Expected if the hypothesis holds: **exit 0, all Firefox specs pass.** No Chromium test ran, so no foreign conversation exists when `restart-persistence` runs.

This is the whole experiment. Step 1 failing and Step 2 passing isolates the variable to "Chromium ran first", because nothing else differs between the two invocations.

- [ ] **Step 3: Confirm the seed ran exactly once in the full run**

```bash
cd /c/Amol/vibe_coding/CodeAtlas_V2
grep -c "seed" .e2e-tmp/api.log 2>/dev/null || echo "no api.log"
```

Then read `apps/web/e2e/support/fixtures.ts` and confirm `seeded` is declared `{ scope: "worker" }`. A worker fixture is built once per worker; the config runs one worker; therefore one seed for 22 tests. Record the literal line numbers.

- [ ] **Step 4: Record the verdict**

Write `docs/evaluation/e2e-isolation.md` containing: the two commands and their exit codes verbatim, the pass/fail counts, the fixture scope with line numbers, and **one** of:

- `CONFIRMED: cross-project state dependency` — Step 1 failed and Step 2 passed.
- `FALSIFIED` — any other combination. State what actually happened and **stop the plan here**; RV-02's fix would be built on a false premise.

- [ ] **Step 5: Commit**

```bash
git add docs/evaluation/e2e-isolation.md
git commit -m "docs(RV-01): the e2e failure is a state dependency, not a flake"
```

---

### Task RV-02: Make the test assert about its own conversation

Only if RV-01 returned `CONFIRMED`. The test already knows the database is shared — `restart-persistence.spec.ts:41-45` says so — and guards with a page-global count that no longer holds. The fix is to make every assertion name the thread the test created.

**Files:**
- Modify: `apps/web/e2e/restart-persistence.spec.ts:30-40`
- Test: the spec is the test.

**Interfaces:**
- Consumes: RV-01's verdict.
- Produces: a Firefox-green `restart-persistence`, which RV-03 requires.

- [ ] **Step 1: Capture the conversation id before asserting anything**

The spec currently reads the URL *after* the answer arrives (line 46), precisely because `/` may redirect. Capture it right after `waitForURL` instead, and use it to scope the assertions:

```ts
  await page.getByRole("button", { name: "New chat" }).click();
  await page.waitForURL(/\/conversations\/conv_/);
  const conversationUrl = page.url();
  const conversationId = conversationUrl.split("/conversations/")[1];

  // Re-assert we are still on the thread we just created. The database is
  // worker-scoped and shared with every other spec, so a page-global
  // `message-user` locator matches messages this test never sent -- which is
  // exactly how this assertion failed, seeing seven `PaymentService.capture`
  // messages from the Chromium project's specs.
  await expect(page).toHaveURL(new RegExp(conversationId));
  await expect(page.getByTestId("message-user")).toHaveCount(0);
```

- [ ] **Step 2: Re-assert the thread identity after Send, before reading messages**

```ts
  await page.getByRole("button", { name: "Send" }).click();

  await expect(page).toHaveURL(new RegExp(conversationId));
  await expect(page.getByTestId("message-user")).toHaveCount(1);
  await expect(page.getByTestId("message-user")).toContainText(question);
```

`toHaveCount(1)` is the assertion that would have caught the original defect: seven messages is not one, and it fails with a count rather than a confusing text mismatch.

- [ ] **Step 3: Delete the now-redundant later capture**

Remove the `const conversationUrl = page.url();` at what was line 46 and its comment block, since the id is captured earlier now. Leave the restart section otherwise untouched.

- [ ] **Step 4: Run the spec alone — it must still pass**

```bash
cd apps/web
pnpm exec playwright test e2e/restart-persistence.spec.ts --project=firefox > /tmp/rv02_alone.txt 2>&1; echo "EXIT=$?"
```

Expected: exit 0, 1 passed.

- [ ] **Step 5: Run the FULL suite — this is the actual verification**

```bash
cd apps/web
pnpm exec playwright test > /tmp/rv02_full.txt 2>&1; echo "EXIT=$?"
grep -E "passed|failed|skipped" /tmp/rv02_full.txt | tail -3
```

Expected: **exit 0**, 0 failed, 8 skipped, 14 passed. A pass alone in Step 4 proves nothing; the whole defect is that this test behaves differently after Chromium has run.

- [ ] **Step 6: Mutation-check the new assertion**

Temporarily change `toHaveCount(1)` to `toHaveCount(99)` and re-run Step 4. It MUST fail. Restore it. A test written against a defect that is already fixed passes whether or not it asserts anything.

- [ ] **Step 7: Commit**

```bash
git add apps/web/e2e/restart-persistence.spec.ts
git commit -m "fix(RV-02): restart-persistence asserts about its own conversation"
```

---

### Task RV-03: The full gate, end to end

**Files:** none modified. This task runs a command and records its output.

**Interfaces:**
- Consumes: RV-02's green full Playwright run.
- Produces: a gate exit code that RV-04 to RV-06 depend on.

- [ ] **Step 1: Confirm the tree is clean and no gate is running**

```bash
cd /c/Amol/vibe_coding/CodeAtlas_V2
git status --short
```

Expected: no output. A gate measuring a dirty tree is void.

- [ ] **Step 2: Run it**

```bash
powershell -ExecutionPolicy Bypass -File scripts/check_phase7.ps1 -SkipSync > /tmp/rv03_gate.log 2>&1; echo "GATE_EXIT=$?"
```

Takes roughly 25 minutes: pytest ~16 min, then web lint/types/tests/build, then Playwright.

- [ ] **Step 3: Read the log, not the exit code**

```bash
grep -E "^==>|passed|failed|error" /tmp/rv03_gate.log | tail -30
```

The README records that a gate has been seen reporting exit 0 while its log said otherwise, and that progress dots stopping with no failure summary mean a **terminated process**, not a broken test. Confirm every `==>` step is present and none is missing from the tail.

- [ ] **Step 4: Record**

Append the command, exit code, and per-step results to a scratch note for RV-08. Do not edit tracked files yet — RV-04 runs next and edits would void nothing, but batching the record keeps one source of truth.

---

### Task RV-04: The packaged leg

- [ ] **Step 1: Run it**

```bash
powershell -ExecutionPolicy Bypass -File scripts/check_phase7.ps1 -Package > /tmp/rv04_package.log 2>&1; echo "EXIT=$?"
```

This **rebuilds the package with PyInstaller** (~15 min) and then runs the packaged smoke and security tests against the real binary.

- [ ] **Step 2: Verify the artifact's parser stamp through the binary**

Do not read the version from source. Index a fixture with the packaged executable into a throwaway database and read what it wrote:

```bash
cd /c/Amol/vibe_coding/CodeAtlas_V2
EXE=dist/codeatlas-win64/codeatlas.exe
DB="$TMP/rv04_verify.db"
rm -f "$DB"
ID=$($EXE repo add tests/evaluation/cases/fixtures/java_app --db "$DB" --json | python -c "import sys,json;print(json.load(sys.stdin)['repository_id'])")
$EXE index "$ID" --db "$DB" --json > /dev/null
python -c "
import sqlite3,os
con=sqlite3.connect(os.environ['TMP']+'/rv04_verify.db')
print(con.execute('SELECT parser_bundle_version, chunker_version, resolver_version FROM snapshots').fetchone())
"
rm -f "$DB"
```

Expected: `('1.9.0', '1.1.0', '1.5.0')`. Anything else means the artifact and the tree disagree — the exact defect the closeout found — so stop and raise it.

- [ ] **Step 3: Record the exit code and the stamp.**

---

### Task RV-05: The semantic packaged leg

- [ ] **Step 1: Run it**

```bash
powershell -ExecutionPolicy Bypass -File scripts/check_phase7.ps1 -Semantic -Package > /tmp/rv05_semantic.log 2>&1; echo "EXIT=$?"
```

This installs the `semantic-local` extra if absent, runs `tests/semantic`, regenerates the Phase 7 uplift baseline check, and builds the semantic artifact (~1.05 GB tree).

- [ ] **Step 2: Confirm the two `-Semantic`-gated artifacts still reproduce**

```bash
grep -E "baseline|rerank|--check" /tmp/rv05_semantic.log | tail -10
```

The register carries a row for exactly this: `baseline-phase-7.json` and `rerank-phase-7.json` are `--check`ed **only** under `-Semantic`, and both went stale twice unnoticed. ADR-0078 added a no-extras input digest, but drift from a model or library upgrade still surfaces only here. If either fails to reproduce, that is the row firing — record it, do not regenerate silently.

- [ ] **Step 3: Record the exit code.**

---

### Task RV-06: The performance leg

- [ ] **Step 1: Make the machine quiet, and say so**

`measure_phase7_perf.py` has a quiescence check, but the README records refresh p95 measured between **1.413 s and 2.433 s** on one machine — a range straddling the 2 s target — purely by load. Close other work first, and note in the record whether anything else was running.

- [ ] **Step 2: Run it — NOT with `-SkipWeb`**

```bash
powershell -ExecutionPolicy Bypass -File scripts/check_phase7.ps1 -SkipSync -Perf > /tmp/rv06_perf.log 2>&1; echo "EXIT=$?"
```

`-SkipWeb` **exits the script early** — it means "backend only, then stop" — so combining it with `-Perf` returns 0 having measured nothing.

- [ ] **Step 3: Take a second run separated by other work**

The README's own guidance: a single figure near the threshold is unresolved, and within-session agreement is not evidence of validity (a loaded pair agreed within 26 ms and was 0.68 s from the truth). Run it twice and record both.

- [ ] **Step 4: Record both figures, the hardware, and the load state.** These are packaged, 20-run figures and are the only ones allowed into the README.

---

### Task RV-07: Install, run, uninstall, and prove the PATH reverses

**This step modifies the user's real user PATH.** It is reversible by design and the reversal is the thing being verified. Confirm with the user before running it if they have not already said to.

- [ ] **Step 1: Capture the baseline FIRST**

```powershell
[Environment]::GetEnvironmentVariable("Path","User") | Out-File -FilePath "$env:TEMP\path-before.txt" -Encoding utf8
([Environment]::GetEnvironmentVariable("Path","User") -split ';' | Where-Object { $_ -ne '' }).Count
```

You cannot check a reversal against a baseline you did not keep. Record the entry count; on 2026-08-10 it was 16 → 17.

- [ ] **Step 2: Install**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install_windows.ps1
```

Expected: exit 0, one PATH entry added, no elevation prompt.

- [ ] **Step 3: Prove it resolves from a FRESH shell**

```powershell
codeatlas doctor
```

A fresh shell is the point: it proves the PATH entry took, not that the build directory happens to be the working directory.

- [ ] **Step 4: Prove the server serves and refuses off-loopback**

```powershell
codeatlas serve --web --port 8123
# in another shell:
curl.exe -s -o NUL -w "%{http_code}" http://127.0.0.1:8123/v1/repositories
curl.exe -s -D - -o NUL http://127.0.0.1:8123/ | Select-String "Cache-Control"
```

Expected: `200`, and `Cache-Control: no-store, max-age=0, must-revalidate` on the shell. Use a non-default port so the probe cannot collide with a running server. Stop the server.

- [ ] **Step 5: Uninstall and diff the PATH**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install_windows.ps1 -Uninstall
$before = Get-Content "$env:TEMP\path-before.txt"
$after  = [Environment]::GetEnvironmentVariable("Path","User")
Compare-Object ($before -split ';') ($after -split ';')
```

Expected: **zero differences.** Any output means it did not reverse cleanly, which is a release defect — record it and stop.

- [ ] **Step 6: Confirm the database was not touched**

```powershell
Test-Path "$env:LOCALAPPDATA\CodeAtlas\data\codeatlas.db"
Test-Path "$env:LOCALAPPDATA\CodeAtlas\app"
```

Expected: database `True`, app directory `False`. Uninstalling removes the app and must never remove the user's data.

---

### Task RV-08: Record it, and close the register row honestly

**Files:**
- Modify: `docs/plans/PLAN.md` (row 115, handoff, Active Work), `documentation/memory.md`, `README.md` if the test count moved.

- [ ] **Step 1: Update register row 115 to its true disposition**

If RV-02 landed: the row moves from `DEFERRED` to `CLOSED`, citing RV-01's experiment and RV-02's full-suite green — **and stating that the fix was to the test's isolation assumption, not to the product**, so nobody later reads it as a persistence bug that was fixed.

If RV-01 falsified the hypothesis: the row stays `DEFERRED` and gains the new evidence. Do not close a row on a mechanism you did not demonstrate.

- [ ] **Step 2: Append a handoff entry**

Include, for every leg: the command, the exit code, and the counts. For any leg not run, say so and why — the closeout's merge commit already sets that precedent by naming what it had not verified.

- [ ] **Step 3: Update the README test count only if it moved**

```bash
cd /c/Amol/vibe_coding/CodeAtlas_V2
.venv/Scripts/python.exe -m pytest tests --collect-only -q -p no:cacheprovider 2>&1 | tail -2
```

`passed + skipped` must equal the collected count. RV-02 changes an e2e spec, which pytest does not collect, so this should read **2483** unchanged.

- [ ] **Step 4: Update `documentation/memory.md`** with a resume point naming what is now verified and what is not.

- [ ] **Step 5: Run the doc guards, then commit**

```bash
.venv/Scripts/python.exe -m pytest tests/unit/test_readme_claims.py tests/unit/test_deferred_register.py tests/unit/test_working_tree_line_endings.py -q
git add -A && git commit -m "docs(RV-08): release validation recorded"
```

---

## Self-Review

**Spec coverage.** Every section of the design maps to a task: the blocking analysis → RV-01/RV-02; the four legs → RV-03 to RV-06; step 5 → RV-07; the recording obligation → RV-08. Option (c) quarantine and option (d) accept-red are both represented as ruling points rather than executable steps, because the Global Constraints forbid an executor choosing either alone.

**Placeholder scan.** No "TBD", no "add error handling", no "similar to Task N". Every command is literal and every expected result is stated. RV-02's code blocks are the actual TypeScript.

**Type consistency.** `conversationUrl` and `conversationId` are introduced in RV-02 Step 1 and used in Steps 2 and 3; RV-02 Step 3 removes the original `conversationUrl` declaration so the name is bound exactly once.

**Known gap, stated rather than hidden.** RV-02's fix assumes the page stays on the created conversation once identity is re-asserted. If the app genuinely navigates away — rather than the locator merely matching foreign messages — then the assertion will fail on the URL instead, and that would be a **product** finding requiring a new ADR and a stop. RV-02 Step 5 is where that surfaces.
