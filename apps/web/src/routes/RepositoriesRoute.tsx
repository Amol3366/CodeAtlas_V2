import { useActiveRepository } from "../app/context";
import { Preflight } from "../features/change-analysis/Preflight";
import { RepositoryPanel } from "../features/repositories/RepositoryPanel";

/**
 * Repository registration, indexing, diagnostics, and change preflight.
 *
 * This is intentionally separate from the chat entry route: opening CodeAtlas
 * should land in chat, while indexing stays an explicit action the user can
 * return to from the sidebar.
 */
export function RepositoriesRoute() {
  const { repositoryId, setRepositoryId } = useActiveRepository();

  return (
    <div className="mx-auto max-w-[var(--measure)] p-[var(--space-8)]">
      <RepositoryPanel onSelect={setRepositoryId} />
      <Preflight repositoryId={repositoryId} />
    </div>
  );
}
