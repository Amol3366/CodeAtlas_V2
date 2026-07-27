import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";

import { Skeleton } from "../../components/Skeleton";
import { api, ApiError } from "../../lib/api";
import type { MessageEvidence } from "../../lib/conversations";

/**
 * The evidence drawer (`AGENTS.md` Section 14.1).
 *
 * What a citation must show, and why each part matters:
 *
 * - **the snapshot the answer used**, not the current one, so a historical
 *   message keeps its own label (Section 14.5);
 * - **derivation and confidence as separate facts**, because a high-confidence
 *   heuristic is still a heuristic;
 * - **the excerpt as text**, never as markup — it is raw repository source;
 * - **an explicit invalid state** when the backend cannot re-verify the hash.
 *   Silently showing current file contents under an old citation would be the
 *   exact substitution the evidence contract forbids.
 */

/**
 * `GET /v1/evidence/{id}` answers with the standard query envelope, not a bare
 * evidence object, and it requires the repository whose snapshot the ID
 * belongs to — an evidence ID is only meaningful inside one.
 */
interface EvidenceResponse {
  readonly evidence: readonly {
    readonly evidence_id: string;
    readonly excerpt: string;
    readonly validation: string;
  }[];
}

export interface EvidenceDrawerProps {
  readonly evidence: MessageEvidence | null;
  readonly repositoryId: string | null;
  readonly onClose: () => void;
}

export function EvidenceDrawer({
  evidence,
  repositoryId,
  onClose,
}: EvidenceDrawerProps) {
  const closeButton = useRef<HTMLButtonElement>(null);
  const opener = useRef<Element | null>(null);

  const fetched = useQuery({
    queryKey: ["evidence", repositoryId ?? "", evidence?.evidence_id ?? ""],
    queryFn: () =>
      api.get<EvidenceResponse>(
        `/v1/evidence/${encodeURIComponent(evidence?.evidence_id ?? "")}` +
          `?repository_id=${encodeURIComponent(repositoryId ?? "")}`,
      ),
    enabled: evidence !== null && repositoryId !== null,
    retry: false,
  });

  // Focus moves into the drawer when it opens and returns to whatever opened
  // it when it closes; a keyboard user must never be stranded.
  useEffect(() => {
    if (evidence === null) return undefined;
    opener.current = document.activeElement;
    closeButton.current?.focus();
    return () => {
      (opener.current as HTMLElement | null)?.focus?.();
    };
  }, [evidence]);

  useEffect(() => {
    if (evidence === null) return undefined;
    const onKey = (pressed: KeyboardEvent) => {
      if (pressed.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [evidence, onClose]);

  if (evidence === null) return null;

  // The envelope carries a list; the citation names which member it is. A
  // response that omits it is as much a failure to verify as an error status —
  // showing nothing is the only honest option either way.
  const found = fetched.data?.evidence.find(
    (item) => item.evidence_id === evidence.evidence_id,
  );
  const invalid =
    fetched.isError ||
    (fetched.data !== undefined &&
      (found === undefined || found.validation !== "valid"));

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="evidence-title"
      className="flex h-full flex-col border-l border-border bg-surface-raised p-[var(--space-4)]"
    >
      <div className="flex items-start justify-between gap-[var(--space-2)]">
        <h2 id="evidence-title" className="text-sm font-semibold">
          Evidence [{evidence.citation_ordinal}]
        </h2>
        <button
          ref={closeButton}
          type="button"
          onClick={onClose}
          aria-label="Close evidence"
          className="rounded-[var(--radius-sm)] border border-border px-[var(--space-2)] py-[var(--space-1)] text-xs"
        >
          Close
        </button>
      </div>

      <dl className="mt-[var(--space-3)] grid grid-cols-[auto_1fr] gap-x-[var(--space-3)] gap-y-[var(--space-1)] text-sm">
        <dt className="text-text-muted">File</dt>
        <dd>
          <code>
            {evidence.file_path}:{evidence.start_line}-{evidence.end_line}
          </code>
        </dd>
        {evidence.symbol !== null ? (
          <>
            <dt className="text-text-muted">Symbol</dt>
            <dd>
              <code>{evidence.symbol}</code>
            </dd>
          </>
        ) : null}
        <dt className="text-text-muted">Derivation</dt>
        <dd data-testid="derivation">{evidence.derivation}</dd>
        <dt className="text-text-muted">Confidence</dt>
        <dd>{evidence.confidence.toFixed(2)}</dd>
        <dt className="text-text-muted">Snapshot</dt>
        <dd data-testid="evidence-snapshot">
          <code>{evidence.snapshot_id}</code>
        </dd>
      </dl>

      <div className="mt-[var(--space-4)] min-h-0 flex-1 overflow-auto">
        {fetched.isPending ? (
          <Skeleton className="h-24 w-full" label="Loading excerpt" />
        ) : invalid ? (
          <p role="alert" className="text-sm text-danger">
            This excerpt could not be verified against the snapshot it was cited
            from, so CodeAtlas is not showing it.{" "}
            <code className="text-text-muted">
              {fetched.error instanceof ApiError
                ? fetched.error.code
                : (found?.validation ?? "EVIDENCE_INVALID")}
            </code>
          </p>
        ) : (
          // Raw repository source: rendered as text inside a code block, never
          // parsed as markup.
          <pre className="overflow-x-auto rounded-[var(--radius-md)] bg-surface-sunken p-[var(--space-3)] text-xs">
            <code data-testid="excerpt">{found?.excerpt ?? ""}</code>
          </pre>
        )}
      </div>
    </div>
  );
}
