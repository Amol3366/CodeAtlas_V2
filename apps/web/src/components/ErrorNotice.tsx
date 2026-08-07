import { ApiError } from "../lib/api";

/**
 * The standard error envelope, rendered for a user.
 *
 * Lives in `components/` rather than in a feature: every feature surfaces the
 * same envelope, and a shared control reached across feature boundaries is a
 * shared control in the wrong place.
 */
export function ErrorNotice({ error }: { readonly error: unknown }) {
  // The envelope's code appears beside the message so a user reporting a
  // problem can quote something stable. A stack trace is never rendered.
  const code = error instanceof ApiError ? error.code : "INTERNAL_ERROR";
  const message =
    error instanceof ApiError ? error.message : "The request failed.";
  return (
    <p role="alert" className="mt-[var(--space-3)] text-sm text-danger">
      <span className="font-medium">{message}</span>{" "}
      <code className="text-text-muted">{code}</code>
    </p>
  );
}
