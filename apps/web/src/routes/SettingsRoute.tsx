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
      <div className="mx-auto max-w-[var(--measure)] p-[var(--space-8)]">
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="mt-[var(--space-3)] text-sm text-text-muted">
          Select a repository on the{" "}
          <Link to="/" className="underline">
            home page
          </Link>{" "}
          to configure it.
        </p>
      </div>
    );
  }

  // The id, not a placeholder, while the list is in flight: the name is a
  // nicety and the identity is not.
  const displayName =
    repositories.data?.find((item) => item.repository_id === repositoryId)
      ?.display_name ?? repositoryId;

  return (
    <div className="mx-auto max-w-[var(--measure)] p-[var(--space-8)]">
      <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
      <p className="mt-[var(--space-1)] text-sm text-text-muted">
        Configuring{" "}
        <span data-testid="settings-repository" className="font-medium">
          {displayName}
        </span>
      </p>
      <div className="mt-[var(--space-6)]">
        <SemanticSettings repositoryId={repositoryId} />
      </div>
    </div>
  );
}
