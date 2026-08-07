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
                    <p
                      key={limitation}
                      className="mt-[var(--space-1)] text-xs text-text-muted"
                    >
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
