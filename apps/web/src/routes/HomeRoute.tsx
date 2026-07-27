import { useActiveRepository } from "../app/context";
import { Preflight } from "../features/change-analysis/Preflight";
import { RepositoryPanel } from "../features/repositories/RepositoryPanel";

/**
 * The empty state leads to value rather than decorating a blank page: adding a
 * repository is the only thing that can be done first, and the privacy
 * statement belongs where that decision is made (`AGENTS.md` Section 14.2).
 */
export function HomeRoute() {
  const { repositoryId, setRepositoryId } = useActiveRepository();

  return (
    <div className="mx-auto max-w-[var(--measure)] p-[var(--space-8)]">
      <RepositoryPanel onSelect={setRepositoryId} />
      <Preflight repositoryId={repositoryId} />
    </div>
  );
}
