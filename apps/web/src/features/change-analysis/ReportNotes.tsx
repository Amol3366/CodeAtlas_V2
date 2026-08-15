/**
 * Warnings and limitations — the part that keeps the rest honest.
 *
 * Known codes are explained in plain language, following the 2026-08-04
 * precedent. An unknown code renders as itself: a code nobody has written
 * prose for is still information, and dropping it would quietly shrink what
 * the report disclosed.
 */

const KNOWN_WARNINGS: Readonly<Record<string, string>> = {
  EVIDENCE_EXCERPT_TRUNCATED:
    "Some evidence was too long to show in full and was shortened.",
  LEXICAL_QUERY_RELAXED:
    "The text search was broadened to find matches. Lexical search matches wording, which is not proof of behaviour.",
  FILE_TOO_LARGE:
    "Some files were too large to analyse and were left out of the comparison. Changes inside them were not detected — the limitation below names them.",
};

export function ReportNotes({
  warnings,
  limitations,
}: {
  readonly warnings: readonly string[];
  readonly limitations: readonly string[];
}) {
  if (warnings.length === 0 && limitations.length === 0) return null;

  return (
    <section aria-labelledby="report-notes" className="mt-[var(--space-6)]">
      <h2 id="report-notes" className="text-sm font-semibold">
        Warnings and limitations
      </h2>
      <ul className="mt-[var(--space-2)] space-y-[var(--space-1)] text-sm text-text-muted">
        {warnings.map((code) => (
          <li key={code}>{KNOWN_WARNINGS[code] ?? <code>{code}</code>}</li>
        ))}
        {limitations.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  );
}
