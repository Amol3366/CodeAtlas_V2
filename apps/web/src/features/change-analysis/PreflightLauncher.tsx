import { useState } from "react";

import { ErrorNotice } from "../../components/ErrorNotice";
import { ApiError } from "../../lib/api";
import { useRunCommitRange, useRunWorkingTree } from "./useAnalysis";

type Mode = "working-tree" | "commit-range";

const MODES: readonly (readonly [Mode, string])[] = [
  ["working-tree", "Working tree"],
  ["commit-range", "Commit range"],
];

/**
 * Starts an analysis.
 *
 * Refs are free text on purpose: a ref is anything Git resolves, and a
 * dropdown cannot enumerate that. The frontend does not pre-validate syntax it
 * does not own — the backend answers with `GIT_REF_UNRESOLVABLE`, and the
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
  // is offered for this code. The envelope marks it retryable, which is wrong
  // for this condition; that is recorded as a follow-up rather than changed
  // here.
  const notGit =
    active.error instanceof ApiError &&
    active.error.code === "CHANGE_ANALYSIS_REQUIRES_GIT";

  return (
    <section aria-labelledby="preflight-launcher">
      <h2 id="preflight-launcher" className="text-sm font-semibold">
        Change preflight
      </h2>
      <p className="mt-[var(--space-1)] text-sm text-text-muted">
        Reports what changed, what it may affect, and the evidence for each
        finding.
      </p>

      <fieldset className="mt-[var(--space-3)] border-0 p-0">
        <legend className="text-xs text-text-muted">What to compare</legend>
        {MODES.map(([value, label]) => (
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
          className="ml-[var(--space-2)] rounded-[var(--radius-sm)] border border-border px-[var(--space-2)] py-[var(--space-1)]"
        />
      </label>

      {mode === "commit-range" ? (
        <label className="mt-[var(--space-2)] block text-sm">
          Target ref
          <input
            value={targetRef}
            onChange={(event) => setTargetRef(event.target.value)}
            className="ml-[var(--space-2)] rounded-[var(--radius-sm)] border border-border px-[var(--space-2)] py-[var(--space-1)]"
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
