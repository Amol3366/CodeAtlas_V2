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
export function EvidenceRef({ item }: { readonly item: ChangeEvidenceItem }) {
  return (
    <p className="mt-[var(--space-1)] text-xs text-text-muted">
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
