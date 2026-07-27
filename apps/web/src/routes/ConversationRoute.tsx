import { useParams } from "react-router-dom";

import { useActiveRepository, useCitation } from "../app/context";
import { Thread } from "../features/conversations/Thread";
import { useRepositoryStatus } from "../lib/queries";

/**
 * One thread, identified by the URL so a reload returns to it.
 *
 * The active snapshot is passed down so a message answered against a
 * superseded snapshot can say so; the message keeps its own label rather than
 * borrowing the current one (`AGENTS.md` Section 14.5).
 */
export function ConversationRoute() {
  const { conversationId } = useParams<{ conversationId: string }>();
  const { repositoryId } = useActiveRepository();
  const { setCitation } = useCitation();
  const status = useRepositoryStatus(repositoryId);

  if (conversationId === undefined) return null;

  return (
    <div className="mx-auto flex h-full max-w-[var(--measure)] flex-col p-[var(--space-6)]">
      <Thread
        conversationId={conversationId}
        activeSnapshotId={status.data?.snapshot?.snapshot_id ?? null}
        onCite={(evidence) => setCitation(evidence)}
      />
    </div>
  );
}
