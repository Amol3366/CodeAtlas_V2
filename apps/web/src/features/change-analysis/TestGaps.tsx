import { EvidenceRef } from "./EvidenceRef";
import type { ChangeEvidenceItem, GapReason } from "./useAnalysis";

/**
 * Possible test gaps, each with the reason it is still a gap.
 *
 * The disclaimer is mandatory and never collapsible. A missing `TESTS` edge
 * does not prove absence of coverage, and only executing the suite could cross
 * that line — which CodeAtlas does not do. The heading says "possible" for the
 * same reason.
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
