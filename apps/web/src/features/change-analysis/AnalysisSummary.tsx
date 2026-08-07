import type { AnalysisStateRef, ChangeReport } from "./useAnalysis";

/**
 * The verdict, read first.
 *
 * Freshness is shown because a stale base means the analysis describes a
 * repository that has since moved; hiding it would turn an outdated report
 * into a confident one.
 */
export function AnalysisSummary({ report }: { readonly report: ChangeReport }) {
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
