# First-class Preflight Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote change preflight from a section embedded in another route to a route pair that renders everything the API already returns — changed symbols, impact edges with their derivation, and the test gaps and reasons from ADR-0016 — with evidence shown inline.

**Architecture:** `/preflight` launches an analysis; `/preflight/:analysisId` loads the persisted report by id, so an audit record survives a reload. One 147-line component becomes eight focused ones plus a hooks module. Types come from the generated OpenAPI types, never hand-written. No backend file is touched.

**Tech Stack:** React 18.3, TypeScript 5.7 (strict), Vite 6, TanStack Query 5, Tailwind 4 over `styles/tokens.css`, react-router-dom 6, Vitest + Testing Library + vitest-axe, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-07-preflight-web-screen-design.md`

## Global Constraints

- **Frontend-only.** No file under `src/codeatlas/` may change. No new endpoint.
- `contract_version` stays `"1.1"`; `SCHEMA_VERSION` stays `14`; no migration.
- TypeScript strict. **No `any`** (`documentation/rules.md`).
- Do NOT hand-edit `apps/web/src/lib/api-types.gen.ts`. Do NOT hand-write interfaces duplicating the contract — import from the generated types.
- Do not add a UI component library. Tailwind + `styles/tokens.css` + Radix primitives only.
- Do not add a dependency without asking.
- **Colour is never the only signal.** Every status carries a word or an icon.
- WCAG 2.2 AA is a release requirement: contrast, keyboard, focus, labels.
- `Skeleton` only for data actually in flight. Never fake progress.
- Never claim a symbol is tested or untested.
- Comments explain *why*, not *what*.
- Do NOT delete, skip, or weaken an existing test.
- Components receive props; data fetching lives in `features/*/` hooks (`documentation/architecture.md`).

## Critical fact: every array field is optional

In `api-types.gen.ts`, `ChangeAnalysisReport` declares `findings?`, `changed_files?`, `changed_symbols?`, `impact_edges?`, `test_gaps?`, `test_gap_reasons?`, `evidence?`, `warnings?`, and `limitations?` — all optional, because Pydantic defaults make them non-required in the JSON schema.

TypeScript therefore types them as `T[] | undefined`. **`report.findings.length` throws at runtime.** Every consumer must default: `const findings = report.findings ?? []`.

This is the single most likely source of a crash in this slice.

## Reference: paths and conventions

- Generated types: `apps/web/src/lib/api-types.gen.ts`. Reach a schema with
  `components["schemas"]["ChangeAnalysisReport"]`.
- API client: `apps/web/src/lib/api.ts` exports `api` with `api.get<T>(path)` and `api.post<T>(path, body)`. Errors are `ApiError` with `.code` and `.message`.
- Query hooks convention: `apps/web/src/lib/queries.ts`.
- `Skeleton`: `apps/web/src/components/Skeleton.tsx`.
- Active repository: `useActiveRepository()` from `apps/web/src/app/context.ts`.
- Router: `apps/web/src/app/App.tsx:13-29`.
- Sidebar nav: `apps/web/src/app/Shell.tsx:84-102`.

---

### Task 1: Move `ErrorNotice` into `components/`

`ErrorNotice` is exported from `apps/web/src/features/repositories/RepositoryPanel.tsx:22`, and four other modules already reach across features to import it. This slice would add roughly eight more such imports. Move it first so the new code imports from the right place.

**Files:**
- Create: `apps/web/src/components/ErrorNotice.tsx`
- Modify: `apps/web/src/features/repositories/RepositoryPanel.tsx` (delete the definition, add an import)
- Modify: `apps/web/src/features/conversations/Sidebar.tsx:13`
- Modify: `apps/web/src/features/conversations/Thread.tsx:15`
- Modify: `apps/web/src/routes/HomeRoute.tsx:12`
- Modify: `apps/web/src/features/change-analysis/Preflight.tsx:4`

**Interfaces:**
- Consumes: nothing.
- Produces: `ErrorNotice({ error }: { readonly error: unknown })` exported from `apps/web/src/components/ErrorNotice.tsx`. Later tasks import it from there.

- [ ] **Step 1: Create the component**

Move the implementation verbatim — this is a relocation, not a rewrite. Keep the existing comment, which explains *why* the code is shown beside the message.

```tsx
import { ApiError } from "../lib/api";

/**
 * The standard error envelope, rendered for a user.
 *
 * Lives in `components/` rather than in a feature: every feature surfaces the
 * same envelope, and a shared control reached across feature boundaries is a
 * shared control in the wrong place.
 */
export function ErrorNotice({ error }: { readonly error: unknown }) {
  // The envelope's code appears beside the message so a user reporting a
  // problem can quote something stable. A stack trace is never rendered.
  const code = error instanceof ApiError ? error.code : "INTERNAL_ERROR";
  const message =
    error instanceof ApiError ? error.message : "The request failed.";
  return (
    <p role="alert" className="mt-[var(--space-3)] text-sm text-danger">
      <span className="font-medium">{message}</span>{" "}
      <code className="text-text-muted">{code}</code>
    </p>
  );
}
```

- [ ] **Step 2: Delete the old definition and re-point every import**

In `RepositoryPanel.tsx`, delete lines 22-34 (the `ErrorNotice` function) and add `import { ErrorNotice } from "../../components/ErrorNotice";` with the other imports.

Update the import in each of `Sidebar.tsx`, `Thread.tsx`, `HomeRoute.tsx`, and `Preflight.tsx` to point at the new module. Paths differ by depth — `../../components/ErrorNotice` from a feature file, `../components/ErrorNotice` from a route file.

Verify nothing still imports it from the old location:

```bash
grep -rn "ErrorNotice" apps/web/src --include=*.tsx --include=*.ts | grep RepositoryPanel
```

Expected: only `RepositoryPanel.tsx`'s own import line.

- [ ] **Step 3: Run the web suite**

Run: `cd apps/web && npm run test`
Expected: PASS. This is a pure relocation — any failure means an import path is wrong, not that behaviour changed.

- [ ] **Step 4: Typecheck**

Run: `cd apps/web && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src
git commit -m "refactor: move ErrorNotice into components"
```

---

### Task 2: Types and hooks — `useAnalysis.ts`

One module owning every server interaction for this feature, plus local aliases so no component writes `components["schemas"][...]` inline.

**Files:**
- Create: `apps/web/src/features/change-analysis/useAnalysis.ts`
- Test: `apps/web/src/features/change-analysis/useAnalysis.test.ts`

**Interfaces:**
- Consumes: `api` from `../../lib/api`; generated types.
- Produces:
  - types `ChangeReport`, `Finding`, `ChangedSymbol`, `ChangedFile`, `ImpactEdge`, `GapReason`, `ChangeEvidenceItem`, `AnalysisStateRef`
  - `useAnalysis(analysisId: string | undefined)` → TanStack query of `ChangeReport`
  - `useRunWorkingTree()` → mutation taking `{ repositoryId: string; baseRef: string }`
  - `useRunCommitRange()` → mutation taking `{ repositoryId: string; baseRef: string; targetRef: string }`
  - `evidenceById(report: ChangeReport): Map<string, ChangeEvidenceItem>`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from "vitest";

import { evidenceById } from "./useAnalysis";
import type { ChangeReport } from "./useAnalysis";

function report(overrides: Partial<ChangeReport> = {}): ChangeReport {
  return {
    analysis_id: "a1",
    repository_id: "r1",
    request_id: "q1",
    contract_version: "1.1",
    created_at: "2026-08-07T00:00:00Z",
    kind: "working_tree",
    status: "complete",
    overall_risk: "low",
    base: { ref: "HEAD", commit: "abc", freshness: "fresh" },
    target: { ref: "working-tree", commit: null, freshness: "fresh" },
    ...overrides,
  } as ChangeReport;
}

describe("evidenceById", () => {
  it("indexes evidence so a finding can resolve its citations", () => {
    const item = {
      evidence_id: "e1",
      side: "target",
      file_path: "src/orders.py",
      start_line: 1,
      end_line: 2,
      content_hash: "h",
      derivation: "deterministic",
      confidence: 1,
    };
    const map = evidenceById(report({ evidence: [item] } as Partial<ChangeReport>));
    expect(map.get("e1")?.file_path).toBe("src/orders.py");
  });

  it("returns an empty map when the report carries no evidence", () => {
    // Every array on ChangeAnalysisReport is optional in the generated types.
    // A consumer that assumes an array crashes on a report without one.
    expect(evidenceById(report()).size).toBe(0);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/web && npx vitest run src/features/change-analysis/useAnalysis.test.ts`
Expected: FAIL — the module does not exist.

- [ ] **Step 3: Implement**

```ts
import { useMutation, useQuery } from "@tanstack/react-query";

import { api } from "../../lib/api";
import type { components } from "../../lib/api-types.gen";

/**
 * Server state for change analysis.
 *
 * Every type here aliases the generated contract rather than restating it. The
 * screen this feeds previously hand-wrote its own `ChangeReport` interface,
 * which is how a frontend drifts from a contract it is supposed to consume:
 * nothing fails when the backend adds a field, and nothing fails when it
 * removes one.
 */

export type ChangeReport = components["schemas"]["ChangeAnalysisReport"];
export type Finding = components["schemas"]["Finding"];
export type ChangedSymbol = components["schemas"]["ChangedSymbol"];
export type ChangedFile = components["schemas"]["ChangedFile"];
export type ImpactEdge = components["schemas"]["ImpactEdge"];
export type GapReason = components["schemas"]["GapReason"];
export type ChangeEvidenceItem = components["schemas"]["ChangeEvidenceItem"];
export type AnalysisStateRef = components["schemas"]["AnalysisStateRef"];

export function evidenceById(
  report: ChangeReport,
): Map<string, ChangeEvidenceItem> {
  return new Map(
    (report.evidence ?? []).map((item) => [item.evidence_id, item]),
  );
}

export function useAnalysis(analysisId: string | undefined) {
  return useQuery({
    queryKey: ["change-analysis", analysisId ?? ""],
    queryFn: () =>
      api.get<ChangeReport>(
        `/v1/change-analysis/${encodeURIComponent(analysisId ?? "")}`,
      ),
    enabled: analysisId !== undefined && analysisId !== "",
    // A persisted analysis is an audit record: it cannot change under us, so
    // refetching it would spend a request to receive the same bytes.
    staleTime: Infinity,
    retry: false,
  });
}

export function useRunWorkingTree() {
  return useMutation({
    mutationFn: (input: { repositoryId: string; baseRef: string }) =>
      api.post<ChangeReport>("/v1/change-analysis/working-tree", {
        repository_id: input.repositoryId,
        base_ref: input.baseRef,
      }),
  });
}

export function useRunCommitRange() {
  return useMutation({
    mutationFn: (input: {
      repositoryId: string;
      baseRef: string;
      targetRef: string;
    }) =>
      api.post<ChangeReport>("/v1/change-analysis/commits", {
        repository_id: input.repositoryId,
        base_ref: input.baseRef,
        target_ref: input.targetRef,
      }),
  });
}
```

**Verify the request body field names against the backend before moving on.** Read `src/codeatlas/api/routers/change_analysis.py:43-68` and the request model it binds. If the field names differ from `repository_id` / `base_ref` / `target_ref`, use the real ones and note the correction in your report. Do not change the backend.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd apps/web && npx vitest run src/features/change-analysis/useAnalysis.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/change-analysis
git commit -m "feat: change-analysis types and query hooks from the generated contract"
```

---

### Task 3: `EvidenceRef` — one inline evidence line

**Files:**
- Create: `apps/web/src/features/change-analysis/EvidenceRef.tsx`
- Test: `apps/web/src/features/change-analysis/EvidenceRef.test.tsx`

**Interfaces:**
- Consumes: `ChangeEvidenceItem` from `./useAnalysis`.
- Produces: `EvidenceRef({ item }: { readonly item: ChangeEvidenceItem })`.

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EvidenceRef } from "./EvidenceRef";
import type { ChangeEvidenceItem } from "./useAnalysis";

function item(overrides: Partial<ChangeEvidenceItem> = {}): ChangeEvidenceItem {
  return {
    evidence_id: "e1",
    side: "target",
    file_path: "src/orders.py",
    symbol: "orders.Order.total",
    start_line: 40,
    end_line: 52,
    content_hash: "h",
    derivation: "static_resolved",
    confidence: 0.9,
    ...overrides,
  } as ChangeEvidenceItem;
}

describe("EvidenceRef", () => {
  it("shows where the evidence is", () => {
    render(<EvidenceRef item={item()} />);
    expect(screen.getByText(/src\/orders\.py/)).toBeInTheDocument();
    expect(screen.getByText(/40/)).toBeInTheDocument();
    expect(screen.getByText(/52/)).toBeInTheDocument();
  });

  it("shows derivation and confidence as separate facts", () => {
    // A high confidence score never implies a stronger derivation.
    render(<EvidenceRef item={item()} />);
    expect(screen.getByText(/static_resolved/)).toBeInTheDocument();
    expect(screen.getByText(/0\.90/)).toBeInTheDocument();
  });

  it("labels base-side evidence as historical", () => {
    // Base side is read from a commit and can never be re-verified against
    // the working tree. It is historical, which is not the same as stale.
    render(<EvidenceRef item={item({ side: "base" })} />);
    expect(screen.getByText(/historical/i)).toBeInTheDocument();
  });

  it("does not label target-side evidence as historical", () => {
    render(<EvidenceRef item={item({ side: "target" })} />);
    expect(screen.queryByText(/historical/i)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/web && npx vitest run src/features/change-analysis/EvidenceRef.test.tsx`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement**

```tsx
import type { ChangeEvidenceItem } from "./useAnalysis";

/**
 * One evidence citation, rendered inline.
 *
 * There is deliberately no excerpt and no fetch. `GET /v1/evidence/{id}`
 * re-verifies *stored*, snapshot-scoped evidence; analysis evidence carries a
 * `side` instead of a `snapshot_id`, because the base side of a working tree
 * has no snapshot, only a commit. Routing one through the other would erase
 * that distinction. Location without an excerpt is honest about *where* the
 * evidence is; the user opens the file.
 */
export function EvidenceRef({
  item,
}: {
  readonly item: ChangeEvidenceItem;
}) {
  return (
    <p className="text-xs text-text-muted">
      <code>{item.file_path}</code>{" "}
      <span>
        lines {item.start_line}–{item.end_line}
      </span>
      {item.symbol ? (
        <>
          {" · "}
          <code>{item.symbol}</code>
        </>
      ) : null}
      {" · "}
      {/* The word carries the meaning; any colour only reinforces it. */}
      <span>{item.side === "base" ? "base (historical)" : "target"}</span>
      {" · "}
      <span>{item.derivation}</span>
      {" · "}
      <span>confidence {item.confidence.toFixed(2)}</span>
    </p>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd apps/web && npx vitest run src/features/change-analysis/EvidenceRef.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/change-analysis
git commit -m "feat: inline evidence reference for change analysis"
```

---

### Task 4: `AnalysisSummary` — the verdict header

**Files:**
- Create: `apps/web/src/features/change-analysis/AnalysisSummary.tsx`
- Test: `apps/web/src/features/change-analysis/AnalysisSummary.test.tsx`

**Interfaces:**
- Consumes: `ChangeReport` from `./useAnalysis`.
- Produces: `AnalysisSummary({ report }: { readonly report: ChangeReport })`.

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AnalysisSummary } from "./AnalysisSummary";
import type { ChangeReport } from "./useAnalysis";

function report(overrides: Partial<ChangeReport> = {}): ChangeReport {
  return {
    analysis_id: "a1",
    repository_id: "r1",
    request_id: "q1",
    contract_version: "1.1",
    created_at: "2026-08-07T00:00:00Z",
    kind: "working_tree",
    status: "complete",
    overall_risk: "high",
    base: { ref: "HEAD", commit: "abc1234", freshness: "fresh" },
    target: { ref: "working-tree", commit: null, freshness: "fresh" },
    ...overrides,
  } as ChangeReport;
}

describe("AnalysisSummary", () => {
  it("states the risk as a word, not only a colour", () => {
    render(<AnalysisSummary report={report()} />);
    expect(screen.getByTestId("overall-risk")).toHaveTextContent("high");
  });

  it("shows both refs with their freshness", () => {
    render(<AnalysisSummary report={report()} />);
    expect(screen.getByText(/HEAD/)).toBeInTheDocument();
    expect(screen.getAllByText(/fresh/).length).toBeGreaterThan(0);
  });

  it("counts an absent array as zero rather than crashing", () => {
    // Every array on the report is optional in the generated contract.
    render(<AnalysisSummary report={report()} />);
    expect(screen.getByText(/0 findings/)).toBeInTheDocument();
  });

  it("counts what the report actually carries", () => {
    const withCounts = report({
      changed_symbols: [{}, {}],
      test_gaps: ["orders.Order"],
    } as Partial<ChangeReport>);
    render(<AnalysisSummary report={withCounts} />);
    expect(screen.getByText(/2 symbols/)).toBeInTheDocument();
    expect(screen.getByText(/1 possible test gap/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/web && npx vitest run src/features/change-analysis/AnalysisSummary.test.tsx`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement**

```tsx
import type { AnalysisStateRef, ChangeReport } from "./useAnalysis";

/**
 * The verdict, read first.
 *
 * Freshness is shown because a stale base means the analysis describes a
 * repository that has since moved; hiding it would turn an outdated report
 * into a confident one.
 */
export function AnalysisSummary({
  report,
}: {
  readonly report: ChangeReport;
}) {
  const findings = report.findings ?? [];
  const symbols = report.changed_symbols ?? [];
  const files = report.changed_files ?? [];
  const gaps = report.test_gaps ?? [];

  return (
    <header className="rounded-[var(--radius-lg)] border border-border bg-surface-raised p-[var(--space-4)]">
      <p className="text-sm">
        Overall risk:{" "}
        {/* The word is the signal; colour only reinforces it. */}
        <strong data-testid="overall-risk">{report.overall_risk}</strong>
      </p>
      <p className="mt-[var(--space-2)] text-sm text-text-muted">
        {files.length} {files.length === 1 ? "file" : "files"} ·{" "}
        {symbols.length} {symbols.length === 1 ? "symbol" : "symbols"} ·{" "}
        {findings.length} {findings.length === 1 ? "finding" : "findings"} ·{" "}
        {gaps.length}{" "}
        {gaps.length === 1 ? "possible test gap" : "possible test gaps"}
      </p>
      <dl className="mt-[var(--space-3)] grid gap-[var(--space-2)] text-xs text-text-muted sm:grid-cols-2">
        <StateRef label="Base" state={report.base} />
        <StateRef label="Target" state={report.target} />
      </dl>
    </header>
  );
}

function StateRef({
  label,
  state,
}: {
  readonly label: string;
  readonly state: AnalysisStateRef;
}) {
  return (
    <div>
      <dt className="font-medium">{label}</dt>
      <dd>
        <code>{state.ref}</code> · {state.commit ?? "no commit"} ·{" "}
        {state.freshness}
      </dd>
    </div>
  );
}
```

**Check `AnalysisStateRef`'s real field names** in `api-types.gen.ts` before implementing. If they differ from `ref` / `commit` / `freshness`, use the real ones and note it in your report.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd apps/web && npx vitest run src/features/change-analysis/AnalysisSummary.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/change-analysis
git commit -m "feat: preflight verdict header"
```

---

### Task 5: `FindingsList`

**Files:**
- Create: `apps/web/src/features/change-analysis/FindingsList.tsx`
- Test: `apps/web/src/features/change-analysis/FindingsList.test.tsx`

**Interfaces:**
- Consumes: `Finding`, `ChangeEvidenceItem` from `./useAnalysis`; `EvidenceRef` from `./EvidenceRef`.
- Produces: `FindingsList({ findings, evidence }: { readonly findings: readonly Finding[]; readonly evidence: Map<string, ChangeEvidenceItem> })`.

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FindingsList } from "./FindingsList";
import type { ChangeEvidenceItem, Finding } from "./useAnalysis";

function finding(overrides: Partial<Finding> = {}): Finding {
  return {
    code: "PUBLIC_CONTRACT_CHANGED",
    severity: "high",
    title: "Public contract changed",
    description: "The signature changed.",
    derivation: "static_resolved",
    confidence: 0.9,
    evidence_ids: [],
    ...overrides,
  } as Finding;
}

const noEvidence = new Map<string, ChangeEvidenceItem>();

describe("FindingsList", () => {
  it("says an empty result is not a safety claim", () => {
    render(<FindingsList findings={[]} evidence={noEvidence} />);
    expect(screen.getByText(/not a claim that the change is safe/i)).toBeInTheDocument();
  });

  it("groups findings by severity, most severe first", () => {
    render(
      <FindingsList
        findings={[finding({ severity: "low", title: "Low one" }), finding({ severity: "critical", title: "Critical one" })]}
        evidence={noEvidence}
      />,
    );
    const headings = screen.getAllByRole("heading", { level: 3 });
    expect(headings[0]).toHaveTextContent(/critical/i);
  });

  it("shows derivation and confidence as separate facts", () => {
    render(<FindingsList findings={[finding()]} evidence={noEvidence} />);
    expect(screen.getByText(/static_resolved/)).toBeInTheDocument();
    expect(screen.getByText(/0\.90/)).toBeInTheDocument();
  });

  it("renders an evidence reference for each cited id", () => {
    const evidence = new Map<string, ChangeEvidenceItem>([
      [
        "e1",
        {
          evidence_id: "e1",
          side: "target",
          file_path: "src/orders.py",
          symbol: null,
          start_line: 1,
          end_line: 2,
          content_hash: "h",
          derivation: "deterministic",
          confidence: 1,
        } as ChangeEvidenceItem,
      ],
    ]);
    render(<FindingsList findings={[finding({ evidence_ids: ["e1"] })]} evidence={evidence} />);
    expect(screen.getByText(/src\/orders\.py/)).toBeInTheDocument();
  });

  it("silently skips a citation whose evidence is absent", () => {
    // Rendering a placeholder for missing evidence would invent a citation.
    render(<FindingsList findings={[finding({ evidence_ids: ["missing"] })]} evidence={noEvidence} />);
    expect(screen.getByText("Public contract changed")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/web && npx vitest run src/features/change-analysis/FindingsList.test.tsx`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement**

```tsx
import { EvidenceRef } from "./EvidenceRef";
import type { ChangeEvidenceItem, Finding } from "./useAnalysis";

const SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"] as const;

/**
 * Findings, most severe first.
 *
 * `derivation` and `confidence` are rendered as separate fields because they
 * are separate facts: a high-confidence heuristic is still a heuristic, and a
 * score never promotes a candidate.
 */
export function FindingsList({
  findings,
  evidence,
}: {
  readonly findings: readonly Finding[];
  readonly evidence: Map<string, ChangeEvidenceItem>;
}) {
  if (findings.length === 0) {
    return (
      <p className="text-sm text-text-muted">
        No findings. That is not a claim that the change is safe — only that no
        rule matched it.
      </p>
    );
  }

  return (
    <>
      {SEVERITY_ORDER.filter((severity) =>
        findings.some((item) => item.severity === severity),
      ).map((severity) => (
        <section key={severity} className="mt-[var(--space-3)]">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-text-muted">
            {severity}
          </h3>
          <ul className="mt-[var(--space-1)] space-y-[var(--space-2)]">
            {findings
              .filter((item) => item.severity === severity)
              .map((item) => (
                <li
                  key={`${item.code}-${item.title}`}
                  className="rounded-[var(--radius-md)] border border-border p-[var(--space-3)]"
                >
                  <p className="text-sm font-medium">{item.title}</p>
                  <p className="mt-[var(--space-1)] text-sm text-text-muted">
                    {item.description}
                  </p>
                  <p className="mt-[var(--space-1)] text-xs text-text-muted">
                    <code>{item.code}</code> · {item.derivation} · confidence{" "}
                    {item.confidence.toFixed(2)}
                  </p>
                  {item.remediation ? (
                    <p className="mt-[var(--space-1)] text-xs">
                      Remediation: {item.remediation}
                    </p>
                  ) : null}
                  {(item.limitations ?? []).map((limitation) => (
                    <p key={limitation} className="mt-[var(--space-1)] text-xs text-text-muted">
                      Limitation: {limitation}
                    </p>
                  ))}
                  {(item.evidence_ids ?? []).map((id) => {
                    const cited = evidence.get(id);
                    // A citation whose evidence is absent is skipped, never
                    // shown as a placeholder: inventing a citation is worse
                    // than omitting one.
                    return cited ? <EvidenceRef key={id} item={cited} /> : null;
                  })}
                </li>
              ))}
          </ul>
        </section>
      ))}
    </>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd apps/web && npx vitest run src/features/change-analysis/FindingsList.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/change-analysis
git commit -m "feat: findings list grouped by severity"
```

---

### Task 6: `ChangedSymbols` and `ImpactList`

Two small components in one task — they are siblings over the same report and a reviewer would accept or reject them together.

**Files:**
- Create: `apps/web/src/features/change-analysis/ChangedSymbols.tsx`
- Create: `apps/web/src/features/change-analysis/ImpactList.tsx`
- Test: `apps/web/src/features/change-analysis/ChangedSymbols.test.tsx`
- Test: `apps/web/src/features/change-analysis/ImpactList.test.tsx`

**Interfaces:**
- Consumes: `ChangedSymbol`, `ChangedFile`, `ImpactEdge` from `./useAnalysis`.
- Produces:
  - `ChangedSymbols({ symbols, files }: { readonly symbols: readonly ChangedSymbol[]; readonly files: readonly ChangedFile[] })`
  - `ImpactList({ edges }: { readonly edges: readonly ImpactEdge[] })`

- [ ] **Step 1: Write the failing tests**

```tsx
// ChangedSymbols.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ChangedSymbols } from "./ChangedSymbols";
import type { ChangedFile, ChangedSymbol } from "./useAnalysis";

describe("ChangedSymbols", () => {
  it("shows each changed symbol with its file and lines", () => {
    const symbol = {
      qualified_name: "orders.Order.total",
      symbol_kind: "METHOD",
      change_kind: "modified",
      file_path: "src/orders.py",
      target_start_line: 40,
      target_end_line: 52,
    } as ChangedSymbol;
    render(<ChangedSymbols symbols={[symbol]} files={[]} />);
    expect(screen.getByText("orders.Order.total")).toBeInTheDocument();
    expect(screen.getByText(/src\/orders\.py/)).toBeInTheDocument();
  });

  it("lists a changed file that produced no symbol", () => {
    // A deleted config file is a real change with no symbol to attach to.
    const file = { path: "pyproject.toml", change_kind: "modified" } as ChangedFile;
    render(<ChangedSymbols symbols={[]} files={[file]} />);
    expect(screen.getByText("pyproject.toml")).toBeInTheDocument();
  });

  it("does not repeat a file that already has a changed symbol", () => {
    const symbol = {
      qualified_name: "orders.Order.total",
      symbol_kind: "METHOD",
      change_kind: "modified",
      file_path: "src/orders.py",
      target_start_line: 40,
      target_end_line: 52,
    } as ChangedSymbol;
    const file = { path: "src/orders.py", change_kind: "modified" } as ChangedFile;
    render(<ChangedSymbols symbols={[symbol]} files={[file]} />);
    expect(screen.getAllByText(/src\/orders\.py/)).toHaveLength(1);
  });

  it("says so when nothing differs", () => {
    render(<ChangedSymbols symbols={[]} files={[]} />);
    expect(screen.getByText(/No files differ/i)).toBeInTheDocument();
  });
});
```

```tsx
// ImpactList.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ImpactList } from "./ImpactList";
import type { ImpactEdge } from "./useAnalysis";

function edge(overrides: Partial<ImpactEdge> = {}): ImpactEdge {
  return {
    source: "orders.Order.total",
    kind: "CALLS",
    target: "api.checkout",
    derivation: "static_resolved",
    ...overrides,
  } as ImpactEdge;
}

describe("ImpactList", () => {
  it("shows source, relation and target", () => {
    render(<ImpactList edges={[edge()]} />);
    expect(screen.getByText(/orders\.Order\.total/)).toBeInTheDocument();
    expect(screen.getByText(/CALLS/)).toBeInTheDocument();
    expect(screen.getByText(/api\.checkout/)).toBeInTheDocument();
  });

  it("shows the derivation on EVERY edge", () => {
    // ADR-0016: a fixture-mediated TESTS edge is a candidate, not coverage.
    // Rendering an edge without its derivation would undo that distinction.
    render(
      <ImpactList
        edges={[
          edge(),
          edge({ kind: "TESTS", target: "test_total", derivation: "low_confidence_heuristic" }),
        ]}
      />,
    );
    expect(screen.getByText(/static_resolved/)).toBeInTheDocument();
    expect(screen.getByText(/low_confidence_heuristic/)).toBeInTheDocument();
  });

  it("renders nothing when there are no edges", () => {
    const { container } = render(<ImpactList edges={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd apps/web && npx vitest run src/features/change-analysis/ChangedSymbols.test.tsx src/features/change-analysis/ImpactList.test.tsx`
Expected: FAIL — modules do not exist.

- [ ] **Step 3: Implement `ChangedSymbols`**

```tsx
import type { ChangedFile, ChangedSymbol } from "./useAnalysis";

/**
 * What changed.
 *
 * Files appear only when they produced no changed symbol. A deleted
 * configuration file is a real change with nothing to attach to, and dropping
 * it would under-report the diff; repeating a file that already has symbols
 * would pad it.
 */
export function ChangedSymbols({
  symbols,
  files,
}: {
  readonly symbols: readonly ChangedSymbol[];
  readonly files: readonly ChangedFile[];
}) {
  const covered = new Set(symbols.map((item) => item.file_path));
  const bare = files.filter((item) => !covered.has(item.path));

  if (symbols.length === 0 && bare.length === 0) {
    return (
      <p className="text-sm text-text-muted">
        No files differ between the two states.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <ul className="space-y-[var(--space-2)]">
        {symbols.map((item) => (
          <li key={`${item.file_path}:${item.qualified_name}`} className="text-sm">
            <code className="font-medium">{item.qualified_name}</code>{" "}
            <span className="text-text-muted">
              {item.symbol_kind} · {item.change_kind} · {item.file_path}
              {item.target_start_line !== null &&
              item.target_start_line !== undefined
                ? ` ${item.target_start_line}–${item.target_end_line}`
                : ""}
            </span>
          </li>
        ))}
        {bare.map((item) => (
          <li key={item.path} className="text-sm">
            <code className="font-medium">{item.path}</code>{" "}
            <span className="text-text-muted">{item.change_kind}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

**Check `ChangedFile`'s and `ChangedSymbol`'s real field names** in `api-types.gen.ts` first (`path` vs `file_path`, and the line-range field names). Use the real ones; note any correction in your report.

- [ ] **Step 4: Implement `ImpactList`**

```tsx
import type { ImpactEdge } from "./useAnalysis";

/**
 * What the change reaches.
 *
 * Every edge shows its derivation. This is where ADR-0016 becomes visible: a
 * fixture-mediated `TESTS` edge carries `low_confidence_heuristic`, so "a test
 * you should probably run" can never read as "a test that covers this".
 */
export function ImpactList({
  edges,
}: {
  readonly edges: readonly ImpactEdge[];
}) {
  if (edges.length === 0) return null;

  return (
    <div className="overflow-x-auto">
      <ul className="space-y-[var(--space-1)]">
        {edges.map((edge) => (
          <li
            key={`${edge.source}-${edge.kind}-${edge.target}`}
            className="text-sm"
          >
            <code>{edge.source}</code>{" "}
            <span className="text-text-muted">→ {edge.kind} →</span>{" "}
            <code>{edge.target}</code>{" "}
            <span className="text-xs text-text-muted">{edge.derivation}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd apps/web && npx vitest run src/features/change-analysis/ChangedSymbols.test.tsx src/features/change-analysis/ImpactList.test.tsx`
Expected: PASS.

- [ ] **Step 6: Mutation-check the derivation requirement**

Temporarily delete the `{edge.derivation}` span from `ImpactList`. Confirm `shows the derivation on EVERY edge` FAILS. Restore it and confirm it passes. This is the assertion that keeps ADR-0016's distinction visible; if removing the rendering breaks no test, the guarantee is not implemented.

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/features/change-analysis
git commit -m "feat: changed symbols and impact edges with derivation"
```

---

### Task 7: The honesty surfaces — `TestGaps` and `ReportNotes`

Both components render what CodeAtlas could *not* determine. They belong together: a reviewer judging one would judge the other by the same standard.

**Files:**
- Create: `apps/web/src/features/change-analysis/TestGaps.tsx`
- Create: `apps/web/src/features/change-analysis/ReportNotes.tsx`
- Test: `apps/web/src/features/change-analysis/TestGaps.test.tsx`
- Test: `apps/web/src/features/change-analysis/ReportNotes.test.tsx`

**Interfaces:**
- Consumes: `GapReason`, `ChangeEvidenceItem` from `./useAnalysis`; `EvidenceRef` from `./EvidenceRef`.
- Produces:
  - `TestGaps({ gaps, reasons, evidence }: { readonly gaps: readonly string[]; readonly reasons: readonly GapReason[]; readonly evidence: Map<string, ChangeEvidenceItem> })`
  - `ReportNotes({ warnings, limitations }: { readonly warnings: readonly string[]; readonly limitations: readonly string[] })`

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TestGaps } from "./TestGaps";
import type { ChangeEvidenceItem, GapReason } from "./useAnalysis";

const noEvidence = new Map<string, ChangeEvidenceItem>();

function reason(overrides: Partial<GapReason> = {}): GapReason {
  return {
    qualified_name: "orders.Order",
    reason: "FIXTURE_MEDIATED_ONLY",
    explanation: "A test reaches this only through a fixture.",
    evidence_ids: [],
    ...overrides,
  } as GapReason;
}

describe("TestGaps", () => {
  it("renders nothing when there are no gaps", () => {
    const { container } = render(
      <TestGaps gaps={[]} reasons={[]} evidence={noEvidence} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("always shows the disclaimer when any gap is shown", () => {
    // CodeAtlas does not execute tests and cannot claim a symbol is untested.
    render(
      <TestGaps gaps={["orders.Order"]} reasons={[reason()]} evidence={noEvidence} />,
    );
    expect(screen.getByText(/does not prove absence of coverage/i)).toBeInTheDocument();
    expect(screen.getByText(/does not execute tests/i)).toBeInTheDocument();
  });

  it("calls the section possible test gaps, never untested", () => {
    render(
      <TestGaps gaps={["orders.Order"]} reasons={[reason()]} evidence={noEvidence} />,
    );
    expect(screen.getByRole("heading", { name: /possible test gaps/i })).toBeInTheDocument();
    expect(screen.queryByText(/untested/i)).not.toBeInTheDocument();
  });

  it("shows each gap with its reason and explanation", () => {
    render(
      <TestGaps gaps={["orders.Order"]} reasons={[reason()]} evidence={noEvidence} />,
    );
    expect(screen.getByText("orders.Order")).toBeInTheDocument();
    expect(screen.getByText(/FIXTURE_MEDIATED_ONLY/)).toBeInTheDocument();
    expect(screen.getByText(/only through a fixture/i)).toBeInTheDocument();
  });

  it("shows a gap that has no matching reason", () => {
    // The name is real even if no reason accompanied it; dropping it would
    // under-report the gap list.
    render(<TestGaps gaps={["orders.Order"]} reasons={[]} evidence={noEvidence} />);
    expect(screen.getByText("orders.Order")).toBeInTheDocument();
  });

  it("renders no evidence reference for NO_TEST_FILE_REFERENCE", () => {
    // An absence is reported as an absence, never dressed in a citation.
    render(
      <TestGaps
        gaps={["orders.Order"]}
        reasons={[reason({ reason: "NO_TEST_FILE_REFERENCE", evidence_ids: [] })]}
        evidence={noEvidence}
      />,
    );
    expect(screen.queryByText(/lines/)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/web && npx vitest run src/features/change-analysis/TestGaps.test.tsx`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement**

```tsx
import { EvidenceRef } from "./EvidenceRef";
import type { ChangeEvidenceItem, GapReason } from "./useAnalysis";

/**
 * Possible test gaps, each with the reason it is still a gap.
 *
 * The disclaimer is mandatory and never collapsible. A missing `TESTS` edge
 * does not prove absence of coverage, and only executing the suite could cross
 * that line — which CodeAtlas does not do. The heading says "possible"
 * for the same reason.
 */
export function TestGaps({
  gaps,
  reasons,
  evidence,
}: {
  readonly gaps: readonly string[];
  readonly reasons: readonly GapReason[];
  readonly evidence: Map<string, ChangeEvidenceItem>;
}) {
  if (gaps.length === 0) return null;

  const byName = new Map(reasons.map((item) => [item.qualified_name, item]));

  return (
    <section aria-labelledby="test-gaps" className="mt-[var(--space-6)]">
      <h2 id="test-gaps" className="text-sm font-semibold">
        Possible test gaps
      </h2>
      <p className="mt-[var(--space-1)] text-sm text-text-muted">
        A missing <code>TESTS</code> edge does not prove absence of coverage.
        CodeAtlas does not execute tests and cannot claim any symbol is
        uncovered.
      </p>
      <ul className="mt-[var(--space-3)] space-y-[var(--space-2)]">
        {gaps.map((name) => {
          const reason = byName.get(name);
          return (
            <li
              key={name}
              className="rounded-[var(--radius-md)] border border-border p-[var(--space-3)]"
            >
              <p className="text-sm font-medium">
                <code>{name}</code>
              </p>
              {reason ? (
                <>
                  <p className="mt-[var(--space-1)] text-xs text-text-muted">
                    <code>{reason.reason}</code>
                  </p>
                  <p className="mt-[var(--space-1)] text-sm text-text-muted">
                    {reason.explanation}
                  </p>
                  {(reason.evidence_ids ?? []).map((id) => {
                    const cited = evidence.get(id);
                    return cited ? <EvidenceRef key={id} item={cited} /> : null;
                  })}
                </>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd apps/web && npx vitest run src/features/change-analysis/TestGaps.test.tsx`
Expected: PASS.

- [ ] **Step 5: Mutation-check the disclaimer**

Temporarily delete the disclaimer paragraph. Confirm `always shows the disclaimer when any gap is shown` FAILS. Restore it and confirm it passes. This is the assertion the product's honesty rests on.

- [ ] **Step 6: Write the failing `ReportNotes` test**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReportNotes } from "./ReportNotes";

describe("ReportNotes", () => {
  it("renders nothing when there is nothing to report", () => {
    const { container } = render(<ReportNotes warnings={[]} limitations={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("explains a known warning code in plain language", () => {
    render(
      <ReportNotes warnings={["EVIDENCE_EXCERPT_TRUNCATED"]} limitations={[]} />,
    );
    expect(screen.getByText(/too long to show in full/i)).toBeInTheDocument();
  });

  it("shows an unknown code as itself rather than dropping it", () => {
    // A code nobody has written prose for is still information. Hiding it
    // would silently shrink what the report disclosed.
    render(<ReportNotes warnings={["SOME_NEW_CODE"]} limitations={[]} />);
    expect(screen.getByText("SOME_NEW_CODE")).toBeInTheDocument();
  });

  it("renders limitations verbatim", () => {
    // Limitations are already prose from the backend, not codes.
    render(
      <ReportNotes warnings={[]} limitations={["Impact expansion stopped at the depth bound."]} />,
    );
    expect(screen.getByText(/stopped at the depth bound/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 7: Run it to verify it fails**

Run: `cd apps/web && npx vitest run src/features/change-analysis/ReportNotes.test.tsx`
Expected: FAIL — module does not exist.

- [ ] **Step 8: Implement `ReportNotes`**

```tsx
/**
 * Warnings and limitations — the part that keeps the rest honest.
 *
 * Known codes are explained in plain language, following the 2026-08-04
 * precedent. An unknown code renders as itself: a code nobody has written
 * prose for is still information, and dropping it would quietly shrink what
 * the report disclosed.
 */

const KNOWN_WARNINGS: Readonly<Record<string, string>> = {
  EVIDENCE_EXCERPT_TRUNCATED:
    "Some evidence was too long to show in full and was shortened.",
  LEXICAL_QUERY_RELAXED:
    "The text search was broadened to find matches. Lexical search matches wording, which is not proof of behaviour.",
};

export function ReportNotes({
  warnings,
  limitations,
}: {
  readonly warnings: readonly string[];
  readonly limitations: readonly string[];
}) {
  if (warnings.length === 0 && limitations.length === 0) return null;

  return (
    <section aria-labelledby="report-notes" className="mt-[var(--space-6)]">
      <h2 id="report-notes" className="text-sm font-semibold">
        Warnings and limitations
      </h2>
      <ul className="mt-[var(--space-2)] space-y-[var(--space-1)] text-sm text-text-muted">
        {warnings.map((code) => (
          <li key={code}>
            {KNOWN_WARNINGS[code] ?? <code>{code}</code>}
          </li>
        ))}
        {limitations.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  );
}
```

- [ ] **Step 9: Run both suites to verify they pass**

Run: `cd apps/web && npx vitest run src/features/change-analysis/TestGaps.test.tsx src/features/change-analysis/ReportNotes.test.tsx`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add apps/web/src/features/change-analysis
git commit -m "feat: test gaps, coverage disclaimer, and plain-language report notes"
```

---

### Task 8: `PreflightLauncher`

**Files:**
- Create: `apps/web/src/features/change-analysis/PreflightLauncher.tsx`
- Test: `apps/web/src/features/change-analysis/PreflightLauncher.test.tsx`

**Interfaces:**
- Consumes: `useRunWorkingTree`, `useRunCommitRange` from `./useAnalysis`; `ErrorNotice` from `../../components/ErrorNotice`.
- Produces: `PreflightLauncher({ repositoryId, onAnalysed }: { readonly repositoryId: string | null; readonly onAnalysed: (analysisId: string) => void })`.

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { PreflightLauncher } from "./PreflightLauncher";

// Follow this file's existing provider-wrapping convention — check how other
// tests in apps/web/src wrap components needing a QueryClient, and reuse it.
describe("PreflightLauncher", () => {
  it("disables running without a repository and says why", () => {
    render(<PreflightLauncher repositoryId={null} onAnalysed={vi.fn()} />);
    expect(screen.getByRole("button", { name: /run preflight/i })).toBeDisabled();
    expect(screen.getByText(/select a repository/i)).toBeInTheDocument();
  });

  it("offers a commit range as well as the working tree", async () => {
    render(<PreflightLauncher repositoryId="r1" onAnalysed={vi.fn()} />);
    await userEvent.click(screen.getByRole("radio", { name: /commit range/i }));
    expect(screen.getByLabelText(/base ref/i)).toHaveValue("HEAD~1");
    expect(screen.getByLabelText(/target ref/i)).toHaveValue("HEAD");
  });

  it("defaults the working-tree base to HEAD", () => {
    render(<PreflightLauncher repositoryId="r1" onAnalysed={vi.fn()} />);
    expect(screen.getByLabelText(/base ref/i)).toHaveValue("HEAD");
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/web && npx vitest run src/features/change-analysis/PreflightLauncher.test.tsx`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement**

```tsx
import { useState } from "react";

import { ErrorNotice } from "../../components/ErrorNotice";
import { ApiError } from "../../lib/api";
import { useRunCommitRange, useRunWorkingTree } from "./useAnalysis";

type Mode = "working-tree" | "commit-range";

/**
 * Starts an analysis.
 *
 * Refs are free text on purpose: a ref is anything Git resolves, and a
 * dropdown cannot enumerate that. The frontend does not pre-validate syntax it
 * does not own — the backend answers with `GIT_REF_UNRESOLVABLE` and the
 * entered refs are preserved so a typo can be corrected rather than retyped.
 */
export function PreflightLauncher({
  repositoryId,
  onAnalysed,
}: {
  readonly repositoryId: string | null;
  readonly onAnalysed: (analysisId: string) => void;
}) {
  const [mode, setMode] = useState<Mode>("working-tree");
  const [baseRef, setBaseRef] = useState("HEAD");
  const [targetRef, setTargetRef] = useState("HEAD");

  const workingTree = useRunWorkingTree();
  const commitRange = useRunCommitRange();
  const active = mode === "working-tree" ? workingTree : commitRange;

  function selectMode(next: Mode) {
    setMode(next);
    // A range needs two distinct commits; the working tree compares against
    // HEAD itself. Switching modes without moving the default would leave a
    // range whose ends are identical.
    setBaseRef(next === "commit-range" ? "HEAD~1" : "HEAD");
    setTargetRef("HEAD");
  }

  function run() {
    if (repositoryId === null) return;
    const onSuccess = (report: { analysis_id: string }) =>
      onAnalysed(report.analysis_id);
    if (mode === "working-tree") {
      workingTree.mutate({ repositoryId, baseRef }, { onSuccess });
    } else {
      commitRange.mutate({ repositoryId, baseRef, targetRef }, { onSuccess });
    }
  }

  // A directory does not become a Git repository by asking twice, so no retry
  // is offered for this code — the envelope marks it retryable, which is wrong
  // for this condition (recorded as a follow-up rather than changed here).
  const notGit =
    active.error instanceof ApiError &&
    active.error.code === "CHANGE_ANALYSIS_REQUIRES_GIT";

  return (
    <section aria-labelledby="preflight-launcher">
      <h2 id="preflight-launcher" className="text-sm font-semibold">
        Change preflight
      </h2>

      <fieldset className="mt-[var(--space-3)]">
        <legend className="text-xs text-text-muted">What to compare</legend>
        {(
          [
            ["working-tree", "Working tree"],
            ["commit-range", "Commit range"],
          ] as const
        ).map(([value, label]) => (
          <label key={value} className="mr-[var(--space-4)] text-sm">
            <input
              type="radio"
              name="preflight-mode"
              checked={mode === value}
              onChange={() => selectMode(value)}
            />{" "}
            {label}
          </label>
        ))}
      </fieldset>

      <label className="mt-[var(--space-3)] block text-sm">
        Base ref
        <input
          value={baseRef}
          onChange={(event) => setBaseRef(event.target.value)}
          className="ml-[var(--space-2)] rounded-[var(--radius-sm)] border border-border px-[var(--space-2)]"
        />
      </label>

      {mode === "commit-range" ? (
        <label className="mt-[var(--space-2)] block text-sm">
          Target ref
          <input
            value={targetRef}
            onChange={(event) => setTargetRef(event.target.value)}
            className="ml-[var(--space-2)] rounded-[var(--radius-sm)] border border-border px-[var(--space-2)]"
          />
        </label>
      ) : null}

      {repositoryId === null ? (
        <p className="mt-[var(--space-2)] text-sm text-text-muted">
          Select a repository to run a preflight.
        </p>
      ) : null}

      <button
        type="button"
        disabled={repositoryId === null || active.isPending}
        onClick={run}
        className="mt-[var(--space-3)] rounded-[var(--radius-md)] border border-border px-[var(--space-3)] py-[var(--space-1)] text-sm disabled:opacity-50"
      >
        {active.isPending ? "Analyzing…" : "Run preflight"}
      </button>

      {active.isError ? <ErrorNotice error={active.error} /> : null}
      {notGit ? (
        <p className="mt-[var(--space-1)] text-sm text-text-muted">
          That repository is not a Git repository, so there is no base state to
          compare against. Running it again will not change that.
        </p>
      ) : null}
    </section>
  );
}
```

Check `ApiError`'s exported shape in `apps/web/src/lib/api.ts` before relying on `.code`; `ErrorNotice` already reads it that way, so the property exists.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd apps/web && npx vitest run src/features/change-analysis/PreflightLauncher.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/features/change-analysis
git commit -m "feat: preflight launcher with working-tree and commit-range modes"
```

---

### Task 9: Routes, navigation, and removing the old mount

**Files:**
- Create: `apps/web/src/routes/PreflightRoute.tsx`
- Create: `apps/web/src/routes/PreflightAnalysisRoute.tsx`
- Test: `apps/web/src/routes/PreflightAnalysisRoute.test.tsx`
- Modify: `apps/web/src/app/App.tsx:13-29` (add both routes **before** the `*` catch-all)
- Modify: `apps/web/src/app/Shell.tsx:84-102` (fourth `NavLink`)
- Modify: `apps/web/src/routes/RepositoriesRoute.tsx` (remove the `<Preflight>` mount, add a link)
- Delete: `apps/web/src/features/change-analysis/Preflight.tsx`
- Delete: `apps/web/src/features/change-analysis/Preflight.test.tsx`

**Interfaces:**
- Consumes: every component from Tasks 2-8.
- Produces: routes `/preflight` and `/preflight/:analysisId`.

- [ ] **Step 1: Write the failing test**

```tsx
import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PreflightAnalysisRoute } from "./PreflightAnalysisRoute";

// `renderAt` must mount the component at `/preflight/a1` with a QueryClient
// and a router. Read `HomeRoute.test.tsx` and `SettingsRoute.test.tsx` first
// and reuse whatever wrapper they already use — do not invent a new one.
// `stubGet` must make `api.get` resolve or reject for the analysis endpoint;
// follow how the existing route tests stub the client.

describe("PreflightAnalysisRoute", () => {
  it("renders a persisted analysis loaded by id", async () => {
    stubGet({
      analysis_id: "a1",
      repository_id: "r1",
      request_id: "q1",
      contract_version: "1.1",
      created_at: "2026-08-07T00:00:00Z",
      kind: "working_tree",
      status: "complete",
      overall_risk: "high",
      base: { ref: "HEAD", commit: "abc1234", freshness: "fresh" },
      target: { ref: "working-tree", commit: null, freshness: "fresh" },
      findings: [],
    });

    renderAt("/preflight/a1", <PreflightAnalysisRoute />);

    expect(await screen.findByTestId("overall-risk")).toHaveTextContent("high");
  });

  it("renders a report whose arrays are entirely absent", async () => {
    // Every array on ChangeAnalysisReport is optional in the generated
    // contract. A route that assumes one crashes on a minimal report.
    stubGet({
      analysis_id: "a1",
      repository_id: "r1",
      request_id: "q1",
      contract_version: "1.1",
      created_at: "2026-08-07T00:00:00Z",
      kind: "working_tree",
      status: "complete",
      overall_risk: "low",
      base: { ref: "HEAD", commit: "abc1234", freshness: "fresh" },
      target: { ref: "working-tree", commit: null, freshness: "fresh" },
    });

    renderAt("/preflight/a1", <PreflightAnalysisRoute />);

    expect(await screen.findByTestId("overall-risk")).toHaveTextContent("low");
  });

  it("shows a not-found message and a way back for an unknown id", async () => {
    stubGetRejects();

    renderAt("/preflight/missing", <PreflightAnalysisRoute />);

    expect(
      await screen.findByText(/analysis was not found/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /preflight/i })).toBeInTheDocument();
  });
});
```

The second test is the important one: it is the guard against the optional-array crash described at the top of this plan.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/web && npx vitest run src/routes/PreflightAnalysisRoute.test.tsx`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement `PreflightRoute`**

The launcher. Reads `useActiveRepository()`, renders `<PreflightLauncher>`, and on success calls `navigate(`/preflight/${analysisId}`)`.

- [ ] **Step 4: Implement `PreflightAnalysisRoute`**

Reads `useParams()`, calls `useAnalysis(analysisId)`, and composes in this exact order:

1. `<AnalysisSummary report={report} />`
2. `<FindingsList findings={report.findings ?? []} evidence={evidence} />`
3. `<ChangedSymbols symbols={report.changed_symbols ?? []} files={report.changed_files ?? []} />`
4. `<ImpactList edges={report.impact_edges ?? []} />`
5. `<TestGaps gaps={report.test_gaps ?? []} reasons={report.test_gap_reasons ?? []} evidence={evidence} />`
6. `<ReportNotes warnings={report.warnings ?? []} limitations={report.limitations ?? []} />`

Build the evidence map once with `const evidence = evidenceById(report)` and pass it to the two components that need it.

Default every array at the point of use — `report.findings ?? []` and so on. **A missing default is a runtime crash, not a type error at the call site.**

Each section is a `<section aria-labelledby>` with a heading, so screen-reader navigation follows the visual order.

- [ ] **Step 5: Wire the routes and navigation**

In `App.tsx`, add both entries **before** the `{ path: "*" }` catch-all — the existing comment at line 24 warns that the catch-all swallows anything after it:

```tsx
      { path: "preflight", element: <PreflightRoute /> },
      { path: "preflight/:analysisId", element: <PreflightAnalysisRoute /> },
```

In `Shell.tsx`, add a fourth `NavLink` to `/preflight` beside the existing three. Use ordinary client-side navigation — the Settings link's document navigation exists to defeat a stale Settings bundle and is not a pattern to copy.

- [ ] **Step 6: Remove the old mount and delete the old component**

In `RepositoriesRoute.tsx`, remove the `<Preflight>` element and its import, and add a link to `/preflight` in its place. Then delete `Preflight.tsx` and `Preflight.test.tsx`.

Deleting `Preflight.test.tsx` is correct here: the component it tested no longer exists, and its behaviour is covered by Tasks 4-8. This is the one deletion this plan authorises. Do not delete any other test.

- [ ] **Step 7: Run the full web suite**

Run: `cd apps/web && npm run test` and `cd apps/web && npx tsc --noEmit`
Expected: PASS, no type errors.

- [ ] **Step 8: Commit**

```bash
git add apps/web/src
git commit -m "feat: promote preflight to its own route pair"
```

---

### Task 10: Accessibility, end-to-end, and documentation

**Files:**
- Create: `apps/web/src/routes/PreflightAnalysisRoute.a11y.test.tsx` (or add to the route test, following whichever convention the repo already uses for `vitest-axe`)
- Create: `apps/web/e2e/preflight.spec.ts`
- Modify: `documentation/memory.md`, `docs/plans/PLAN.md`

- [ ] **Step 1: Write the accessibility test**

Render `PreflightAnalysisRoute` with a fully populated report — findings at two severities, changed symbols, impact edges, test gaps with reasons, warnings, and limitations — and assert no axe violations. Follow the existing `vitest-axe` usage in the repo.

- [ ] **Step 2: Write the Playwright spec**

`apps/web/e2e/preflight.spec.ts`: register and index a repository, open `/preflight`, run a working-tree analysis, assert the URL becomes `/preflight/<id>`, reload, and assert the same analysis renders.

Follow the existing specs in `apps/web/e2e/` for fixture and server setup.

**Skip on Chromium, using the repo's existing skip helper**, with the reason stated in the spec: an upstream renderer defect kills the renderer on client-side navigation, already recorded against four other spec files in `documentation/phases.md`. This route navigates client-side after a POST. Declare the skip; do not silently omit the test.

- [ ] **Step 3: Run both**

Run: `cd apps/web && npm run test`
Run the Playwright suite on Firefox using the repo's existing command (check `apps/web/package.json` scripts).

Record actual commands, exit codes, and output.

- [ ] **Step 4: Update the documentation**

- `documentation/memory.md` — append to Completed. Record the `ErrorNotice` move, and add a follow-up: `ChangeAnalysisRequiresGitError` is declared `retryable = True` (`src/codeatlas/domain/errors.py:155`), which is wrong for a condition that cannot change on retry; the screen suppresses retry for that code rather than changing the backend flag.
- `docs/plans/PLAN.md` — **append** a handoff entry. Never rewrite an earlier one.
- `documentation/design.md` — only if a token or component pattern changed. If nothing changed, say so rather than editing for its own sake.

- [ ] **Step 5: Commit**

```bash
git add apps/web docs documentation
git commit -m "test: preflight accessibility and end-to-end coverage"
```

---

## Notes for the implementer

**Test helper names are illustrative.** `report()`, `finding()`, `item()`, and the provider-wrapping in the route and launcher tests describe what each helper must do. Read the neighbouring test files and follow their conventions. The assertions are the contract; the helper names are not.

**Field names must be checked against `api-types.gen.ts`.** This plan names fields as the Python contract spells them, and the generator is faithful, but verify before implementing — particularly `ChangedFile.path`, `ChangedSymbol.file_path`, the line-range fields, and `AnalysisStateRef`. Note any correction in your report; do not change the backend or hand-edit the generated types.

**Line numbers drift.** Every `path:line` reference was accurate at `4167df8`. If a line does not contain what this plan says, locate the construct by name.

**The three invariants that must not be compromised:**
1. Every impact edge renders its derivation (Task 6, mutation-checked).
2. The test-gap disclaimer renders whenever any gap is shown (Task 7, mutation-checked).
3. No hand-written interface duplicates the contract (Task 2).
