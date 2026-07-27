/**
 * The empty state.
 *
 * It leads to value rather than decorating a blank page: adding a repository is
 * the only thing that can be done first, and the privacy statement belongs
 * where the decision is made, not buried in settings
 * (`AGENTS.md` Section 14.2). Repository onboarding lands in P5-06.
 */
export function HomeRoute() {
  return (
    <div className="mx-auto max-w-[var(--measure)] p-[var(--space-8)]">
      <h1 className="text-2xl font-semibold tracking-tight">CodeAtlas</h1>
      <p className="mt-[var(--space-4)] text-text-muted">
        Add a local repository to begin. CodeAtlas indexes it on this machine
        and sends nothing anywhere: no source, no filenames, and no derived
        content leave your computer unless you explicitly enable a provider.
      </p>
    </div>
  );
}
