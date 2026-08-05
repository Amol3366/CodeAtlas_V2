import { useCallback, useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";

import { Sidebar } from "../features/conversations/Sidebar";
import { EvidenceDrawer } from "../features/evidence/EvidenceDrawer";
import { ThemeToggle } from "../features/settings/ThemeToggle";
import type { MessageEvidence } from "../lib/conversations";
import { useRepositories } from "../lib/queries";
import { useReloadOnNewBuild } from "./buildFreshness";
import { ActiveRepositoryContext, CitationContext } from "./context";

const ACTIVE_REPOSITORY_STORAGE_KEY = "codeatlas.activeRepositoryId";

/**
 * The three-region desktop layout of `AGENTS.md` Section 14.1.
 *
 * On wide screens all three regions are visible. Below that the evidence rail
 * becomes an overlay — a 380px panel beside a narrow conversation would leave
 * neither readable — and the sidebar collapses behind a disclosure. The
 * regions are landmarks, so screen-reader navigation and keyboard order follow
 * the visual structure rather than the DOM's accidents.
 */
export function Shell() {
  useReloadOnNewBuild();

  const repositories = useRepositories();
  const [repositoryOverride, setRepositoryOverrideState] = useState<
    string | null
  >(() => readStoredActiveRepository());
  const [citation, setCitation] = useState<MessageEvidence | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const repositoryId =
    repositories.data === undefined
      ? null
      : repositoryOverride !== null &&
          repositories.data.some(
            (repository) => repository.repository_id === repositoryOverride,
          )
        ? repositoryOverride
        : repositories.data[0]?.repository_id ?? null;

  const setRepositoryId = useCallback((nextRepositoryId: string | null) => {
    setRepositoryOverrideState(nextRepositoryId);
    writeStoredActiveRepository(nextRepositoryId);
  }, []);

  useEffect(() => {
    if (repositories.data === undefined || repositoryOverride === null) return;
    if (
      repositories.data.some(
        (repository) => repository.repository_id === repositoryOverride,
      )
    ) {
      return;
    }

    setRepositoryOverrideState(null);
    writeStoredActiveRepository(null);
  }, [repositories.data, repositoryOverride]);

  return (
    <ActiveRepositoryContext.Provider
      value={{ repositoryId, setRepositoryId }}
    >
      <CitationContext.Provider value={{ citation, setCitation }}>
        <div className="grid h-full grid-cols-1 md:grid-cols-[280px_1fr]">
          <nav
            aria-label="Conversations"
            data-open={sidebarOpen ? "true" : "false"}
            className="hidden border-r border-border bg-surface-raised data-[open=true]:absolute data-[open=true]:inset-y-0 data-[open=true]:left-0 data-[open=true]:z-10 data-[open=true]:block data-[open=true]:w-[280px] md:block"
          >
            <div className="p-[var(--space-3)]">
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold tracking-tight">
                  CodeAtlas
                </span>
                <ThemeToggle />
              </div>
              <div className="mt-[var(--space-2)] flex items-center gap-[var(--space-1)]">
                {/* `NavLink` rather than `Link`: it sets aria-current="page" on
                    the active route, the same way the conversation list marks
                    the active thread. */}
                <NavLink
                  to="/"
                  end
                  className="rounded-[var(--radius-sm)] px-[var(--space-2)] py-[var(--space-1)] text-xs text-text-muted hover:bg-surface-sunken aria-[current=page]:bg-surface-sunken aria-[current=page]:font-medium"
                >
                  Chat
                </NavLink>
                <NavLink
                  to="/repositories"
                  className="rounded-[var(--radius-sm)] px-[var(--space-2)] py-[var(--space-1)] text-xs text-text-muted hover:bg-surface-sunken aria-[current=page]:bg-surface-sunken aria-[current=page]:font-medium"
                >
                  Repositories
                </NavLink>
                <NavLink
                  to="/settings"
                  className="rounded-[var(--radius-sm)] px-[var(--space-2)] py-[var(--space-1)] text-xs text-text-muted hover:bg-surface-sunken aria-[current=page]:bg-surface-sunken aria-[current=page]:font-medium"
                >
                  Settings
                </NavLink>
              </div>
            </div>
            <Sidebar repositoryId={repositoryId} />
          </nav>

          <main id="main" className="min-w-0 overflow-y-auto">
            <button
              type="button"
              aria-label="Show conversations"
              aria-expanded={sidebarOpen}
              onClick={() => setSidebarOpen((open) => !open)}
              className="m-[var(--space-2)] rounded-[var(--radius-sm)] border border-border px-[var(--space-2)] py-[var(--space-1)] text-xs md:hidden"
            >
              Conversations
            </button>
            <Outlet />
          </main>

          {/* Rendered only while something is selected. A permanently reserved
              rail spent 380px on an empty panel for the whole session, and the
              conversation is what the width belongs to. */}
          {citation !== null ? (
            <aside
              aria-label="Evidence"
              className="fixed inset-y-0 right-0 z-20 w-full max-w-[420px] animate-[slide-in-right_var(--motion-base)_ease-out] overflow-y-auto border-l border-border bg-surface-raised shadow-md"
            >
              <EvidenceDrawer
                evidence={citation}
                repositoryId={repositoryId}
                onClose={() => setCitation(null)}
              />
            </aside>
          ) : null}
        </div>
      </CitationContext.Provider>
    </ActiveRepositoryContext.Provider>
  );
}

function readStoredActiveRepository(): string | null {
  try {
    return window.localStorage.getItem(ACTIVE_REPOSITORY_STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStoredActiveRepository(repositoryId: string | null): void {
  try {
    if (repositoryId === null) {
      window.localStorage.removeItem(ACTIVE_REPOSITORY_STORAGE_KEY);
      return;
    }
    window.localStorage.setItem(ACTIVE_REPOSITORY_STORAGE_KEY, repositoryId);
  } catch {
    // In-memory context still works if browser storage is blocked.
  }
}
