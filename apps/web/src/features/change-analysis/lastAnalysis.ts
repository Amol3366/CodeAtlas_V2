const STORAGE_KEY = "codeatlas.last-analysis";

/**
 * The most recent analysis id per repository.
 *
 * A report is persisted server-side and addressed by URL, so nothing is lost
 * when the screen unmounts -- but the id lived *only* in the URL, and the
 * sidebar link pointed at the launcher. Navigating away and back therefore
 * looked exactly like the analysis had been discarded, and the only way back
 * was to run it again.
 *
 * Keyed by repository because an analysis belongs to one: switching
 * repositories must never resolve to another repository's report.
 *
 * This is a pointer, not a cache. The report itself stays server state; if the
 * id no longer resolves, the analysis route reports that rather than inventing
 * anything, which is also what happens after the record is deleted.
 */
type Stored = Record<string, string>;

function read(): Stored {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === null) return {};
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return {};
    return Object.fromEntries(
      Object.entries(parsed as Record<string, unknown>).filter(
        (entry): entry is [string, string] => typeof entry[1] === "string",
      ),
    );
  } catch {
    // Blocked or corrupt storage is not an error worth surfacing: the launcher
    // is still one click away.
    return {};
  }
}

export function lastAnalysisId(repositoryId: string | null): string | null {
  if (repositoryId === null) return null;
  return read()[repositoryId] ?? null;
}

export function rememberAnalysis(
  repositoryId: string | null,
  analysisId: string,
): void {
  if (repositoryId === null) return;
  try {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ ...read(), [repositoryId]: analysisId }),
    );
  } catch {
    // Navigation still works for the rest of this session.
  }
}

export function forgetAnalysis(repositoryId: string | null): void {
  if (repositoryId === null) return;
  try {
    const stored = read();
    delete stored[repositoryId];
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(stored));
  } catch {
    // Nothing to do: the pointer is advisory.
  }
}
