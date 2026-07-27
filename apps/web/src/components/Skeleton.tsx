/**
 * A placeholder for data that is genuinely being fetched.
 *
 * Never for progress that is not really happening: a skeleton over a request
 * that was never sent is a lie about the system's state
 * (`AGENTS.md` Section 14.4).
 */
export function Skeleton({
  className = "",
  label,
}: {
  readonly className?: string;
  readonly label: string;
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-label={label}
      className={`animate-pulse rounded-[var(--radius-md)] bg-surface-sunken ${className}`}
    />
  );
}
