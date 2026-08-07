import { Link } from "react-router-dom";

import { useActiveRepository } from "../app/context";
import { RepositoryPanel } from "../features/repositories/RepositoryPanel";

/**
 * Repository registration, indexing, and diagnostics.
 *
 * This is intentionally separate from the chat entry route: opening CodeAtlas
 * should land in chat, while indexing stays an explicit action the user can
 * return to from the sidebar.
 *
 * Preflight is a route of its own. It is linked from here because this is
 * where a user lands after indexing, but it has one home — two rendering paths
 * for one report would drift.
 */
export function RepositoriesRoute() {
  const { setRepositoryId } = useActiveRepository();

  return (
    <div className="mx-auto max-w-[var(--measure)] p-[var(--space-8)]">
      <RepositoryPanel onSelect={setRepositoryId} />
      <p className="mt-[var(--space-6)] text-sm">
        <Link to="/preflight" className="underline">
          Run a change preflight
        </Link>{" "}
        <span className="text-text-muted">
          — see what your working tree changes and what it may affect.
        </span>
      </p>
    </div>
  );
}
