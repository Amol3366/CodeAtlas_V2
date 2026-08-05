import { Link } from "react-router-dom";

import { useActiveRepository } from "../app/context";
import { SemanticSettings } from "../features/settings/SemanticSettings";
import { useRepositories } from "../lib/queries";

/**
 * The settings route.
 *
 * Deliberately thin: `SemanticSettings` owns the provider choice and its
 * disclosure, and this wrapper owns only the question that component cannot
 * answer for itself — *which repository is this?* Context carries an id, so the
 * display name is looked up from the repository list the shell has already
 * fetched.
 *
 * Naming the repository is a requirement rather than a nicety. This is the one
 * screen in CodeAtlas that can cause repository content to leave the machine,
 * and a page that configured whichever repository context happened to hold,
 * without saying which, would make that consequence ambiguous.
 *
 * The repository selector is not duplicated here. It lives in `RepositoryPanel`
 * on the home route, and a second one would be a second place the active
 * repository can change.
 */
export function SettingsRoute() {
  const { repositoryId } = useActiveRepository();
  const repositories = useRepositories();

  if (repositoryId === null) {
    return (
      <div className="min-h-full bg-surface-raised px-[var(--space-4)] py-[var(--space-8)]">
        <section className="mx-auto max-w-2xl rounded-[var(--radius-md)] border border-border bg-surface p-[var(--space-8)] shadow-sm">
          <p className="text-xs font-semibold uppercase text-text-muted">
            Settings
          </p>
          <h1 className="mt-[var(--space-2)] text-2xl font-semibold tracking-tight">
            Choose a repository
          </h1>
          <p className="mt-[var(--space-3)] text-sm text-text-muted">
            Select a repository on the{" "}
            <Link to="/" className="font-medium text-accent underline">
              home page
            </Link>{" "}
            to configure it.
          </p>
        </section>
      </div>
    );
  }

  // The id, not a placeholder, while the list is in flight: the name is a
  // nicety and the identity is not.
  const displayName =
    repositories.data?.find((item) => item.repository_id === repositoryId)
      ?.display_name ?? repositoryId;

  return (
    <div className="min-h-full bg-surface-raised px-[var(--space-4)] py-[var(--space-8)]">
      <div className="mx-auto max-w-6xl">
        <header className="mb-[var(--space-8)] flex flex-col gap-[var(--space-4)] border-b border-border pb-[var(--space-6)] md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase text-text-muted">
              Settings
            </p>
            <h1 className="mt-[var(--space-2)] text-3xl font-semibold tracking-tight">
              Repository settings
            </h1>
            <p className="mt-[var(--space-2)] text-sm text-text-muted">
              Configuring{" "}
              <span
                data-testid="settings-repository"
                className="rounded-[var(--radius-sm)] bg-surface px-[var(--space-2)] py-[var(--space-1)] font-medium text-text"
              >
                {displayName}
              </span>
            </p>
          </div>
          <Link
            to="/repositories"
            className="inline-flex w-fit rounded-[var(--radius-md)] border border-border bg-surface px-[var(--space-3)] py-[var(--space-2)] text-sm font-medium hover:bg-surface-sunken"
          >
            Repositories
          </Link>
        </header>
        <SemanticSettings repositoryId={repositoryId} />
      </div>
    </div>
  );
}
