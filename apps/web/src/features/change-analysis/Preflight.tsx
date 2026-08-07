import { useMutation } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { ErrorNotice } from "../../components/ErrorNotice";

/**
 * The change-preflight experience (`AGENTS.md` Section 14.1).
 *
 * The report is the *persisted* Phase 4 analysis rendered, not a second
 * opinion: re-opening it never re-analyzes, because a stored analysis is an
 * audit record and running it again could quietly produce a different answer
 * for the same question.
 *
 * Findings are grouped by severity, and warnings and limitations are shown
 * rather than tucked away — the point of the product is that uncertainty is
 * visible.
 */

interface Finding {
  readonly code: string;
  readonly severity: string;
  readonly title: string;
  readonly description: string;
  readonly derivation: string;
  readonly confidence: number;
  readonly evidence_ids: readonly string[];
}

interface ChangeReport {
  readonly analysis_id: string;
  readonly status: string;
  readonly overall_risk: string;
  readonly findings: readonly Finding[];
  readonly warnings: readonly string[];
  readonly limitations: readonly string[];
}

const SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"] as const;

export function Preflight({
  repositoryId,
}: {
  readonly repositoryId: string | null;
}) {
  const run = useMutation({
    mutationFn: () =>
      api.post<ChangeReport>("/v1/change-analysis/working-tree", {
        repository_id: repositoryId,
      }),
  });

  return (
    <section aria-labelledby="preflight" className="mt-[var(--space-6)]">
      <h2 id="preflight" className="text-sm font-semibold">
        Change preflight
      </h2>
      <p className="mt-[var(--space-1)] text-sm text-text-muted">
        Compares the working tree against <code>HEAD</code> and reports what
        changed, what it may affect, and the evidence for each finding.
      </p>
      <button
        type="button"
        disabled={repositoryId === null || run.isPending}
        onClick={() => run.mutate()}
        className="mt-[var(--space-3)] rounded-[var(--radius-md)] border border-border px-[var(--space-3)] py-[var(--space-1)] text-sm disabled:opacity-50"
      >
        {run.isPending ? "Analyzing…" : "Run preflight"}
      </button>

      {run.isError ? <ErrorNotice error={run.error} /> : null}

      {run.isSuccess ? (
        <div className="mt-[var(--space-4)]">
          <p className="text-sm">
            Overall risk:{" "}
            {/* The word is the signal; color only reinforces it. */}
            <strong data-testid="overall-risk">{run.data.overall_risk}</strong>
          </p>

          {run.data.findings.length === 0 ? (
            <p className="mt-[var(--space-2)] text-sm text-text-muted">
              No findings. That is not a claim that the change is safe — only
              that no rule matched it.
            </p>
          ) : (
            SEVERITY_ORDER.filter((severity) =>
              run.data.findings.some((finding) => finding.severity === severity),
            ).map((severity) => (
              <section key={severity} className="mt-[var(--space-3)]">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-text-muted">
                  {severity}
                </h3>
                <ul className="mt-[var(--space-1)] space-y-[var(--space-2)]">
                  {run.data.findings
                    .filter((finding) => finding.severity === severity)
                    .map((finding) => (
                      <li
                        key={`${finding.code}-${finding.title}`}
                        className="rounded-[var(--radius-md)] border border-border p-[var(--space-3)]"
                      >
                        <p className="text-sm font-medium">{finding.title}</p>
                        <p className="mt-[var(--space-1)] text-sm text-text-muted">
                          {finding.description}
                        </p>
                        <p className="mt-[var(--space-1)] text-xs text-text-muted">
                          <code>{finding.code}</code> · {finding.derivation} ·
                          confidence {finding.confidence.toFixed(2)}
                        </p>
                      </li>
                    ))}
                </ul>
              </section>
            ))
          )}

          {run.data.warnings.length > 0 ? (
            <div className="mt-[var(--space-4)]">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-text-muted">
                Warnings
              </h3>
              <ul className="mt-[var(--space-1)] text-sm text-stale">
                {run.data.warnings.map((warning) => (
                  <li key={warning}>
                    <code>{warning}</code>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {run.data.limitations.length > 0 ? (
            <div className="mt-[var(--space-4)]">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-text-muted">
                Limitations
              </h3>
              <ul className="mt-[var(--space-1)] text-sm text-text-muted">
                {run.data.limitations.map((limitation) => (
                  <li key={limitation}>{limitation}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
