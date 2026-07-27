import { useParams } from "react-router-dom";

/**
 * One thread, identified by the URL so a reload returns to it.
 *
 * The message list, composer, and streaming arrive in P5-07 and P5-08. This
 * route exists now so routing and the shell can be verified before there is
 * content to get wrong.
 */
export function ConversationRoute() {
  const { conversationId } = useParams<{ conversationId: string }>();

  return (
    <div className="mx-auto max-w-[var(--measure)] p-[var(--space-8)]">
      <h1 className="text-lg font-semibold tracking-tight">Conversation</h1>
      <p className="mt-[var(--space-2)] text-sm text-text-muted">
        <code>{conversationId}</code>
      </p>
    </div>
  );
}
