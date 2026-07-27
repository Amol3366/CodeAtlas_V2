import { createContext, useContext } from "react";

import type { MessageEvidence } from "../lib/conversations";

/**
 * Cross-region state, kept in context because the sidebar, the thread, and the
 * evidence rail are siblings that must agree on one repository and one open
 * citation. Nothing here is server state — that lives in the query cache.
 */

interface ActiveRepository {
  readonly repositoryId: string | null;
  readonly setRepositoryId: (repositoryId: string | null) => void;
}

export const ActiveRepositoryContext = createContext<ActiveRepository>({
  repositoryId: null,
  setRepositoryId: () => undefined,
});

export function useActiveRepository(): ActiveRepository {
  return useContext(ActiveRepositoryContext);
}

interface Citation {
  readonly citation: MessageEvidence | null;
  readonly setCitation: (citation: MessageEvidence | null) => void;
}

export const CitationContext = createContext<Citation>({
  citation: null,
  setCitation: () => undefined,
});

export function useCitation(): Citation {
  return useContext(CitationContext);
}
