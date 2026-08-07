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
