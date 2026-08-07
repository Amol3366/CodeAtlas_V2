import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { Skeleton } from "../../components/Skeleton";
import {
  groupByRecency,
  useArchiveConversation,
  useConversations,
  useCreateConversation,
  useDeleteConversation,
  useRenameConversation,
} from "../../lib/conversations";
import { ErrorNotice } from "../../components/ErrorNotice";

/**
 * The conversation sidebar (`AGENTS.md` Section 14.1).
 *
 * The list comes from the server and is grouped by the server's own
 * timestamps; the search box filters what was fetched rather than pretending to
 * search history that has not been loaded. The active thread is whatever the
 * URL says, so a reload or a shared link lands in the same place.
 */
export function Sidebar({
  repositoryId,
}: {
  readonly repositoryId: string | null;
}) {
  const { conversationId } = useParams<{ conversationId: string }>();
  const navigate = useNavigate();
  const [filter, setFilter] = useState("");
  const [renaming, setRenaming] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");

  const conversations = useConversations(repositoryId);
  const create = useCreateConversation(repositoryId);
  const rename = useRenameConversation(repositoryId);
  const archive = useArchiveConversation(repositoryId);
  const remove = useDeleteConversation(repositoryId);

  if (repositoryId === null) {
    return (
      <p className="p-[var(--space-4)] text-sm text-text-muted">
        Select a repository to see its conversations.
      </p>
    );
  }
  if (conversations.isPending) {
    return (
      <div className="p-[var(--space-4)]">
        <Skeleton className="h-32 w-full" label="Loading conversations" />
      </div>
    );
  }
  if (conversations.isError) {
    return (
      <div className="p-[var(--space-4)]">
        <ErrorNotice error={conversations.error} />
      </div>
    );
  }

  const needle = filter.trim().toLowerCase();
  const visible = conversations.data.items.filter((item) =>
    needle === "" ? true : item.title.toLowerCase().includes(needle),
  );
  const groups = groupByRecency(visible);

  return (
    <div className="flex h-full flex-col p-[var(--space-3)]">
      <button
        type="button"
        onClick={() =>
          create.mutate(undefined, {
            onSuccess: (created) =>
              navigate(`/conversations/${created.conversation_id}`),
          })
        }
        disabled={create.isPending}
        className="rounded-[var(--radius-md)] bg-accent px-[var(--space-3)] py-[var(--space-2)] text-sm font-medium text-accent-contrast disabled:opacity-50"
      >
        New chat
      </button>

      <label htmlFor="conversation-filter" className="sr-only">
        Search conversations
      </label>
      <input
        id="conversation-filter"
        type="search"
        placeholder="Search conversations"
        value={filter}
        onChange={(changed) => setFilter(changed.target.value)}
        className="mt-[var(--space-3)] rounded-[var(--radius-md)] border border-border bg-surface px-[var(--space-2)] py-[var(--space-1)] text-sm"
      />

      {visible.length === 0 ? (
        <p className="mt-[var(--space-4)] text-sm text-text-muted">
          {needle === "" ? "No conversations yet." : "No matching conversations."}
        </p>
      ) : (
        <div className="mt-[var(--space-4)] min-h-0 flex-1 overflow-y-auto">
          {groups.map(([label, items]) => (
            <section key={label} className="mb-[var(--space-4)]">
              <h2 className="px-[var(--space-2)] text-xs font-semibold uppercase tracking-wide text-text-muted">
                {label}
              </h2>
              <ul className="mt-[var(--space-1)]">
                {items.map((item) => (
                  <li key={item.conversation_id}>
                    {renaming === item.conversation_id ? (
                      <form
                        onSubmit={(submitted) => {
                          submitted.preventDefault();
                          rename.mutate({
                            id: item.conversation_id,
                            title: draftTitle,
                          });
                          setRenaming(null);
                        }}
                      >
                        <label
                          htmlFor={`rename-${item.conversation_id}`}
                          className="sr-only"
                        >
                          New title
                        </label>
                        <input
                          id={`rename-${item.conversation_id}`}
                          autoFocus
                          value={draftTitle}
                          onChange={(changed) =>
                            setDraftTitle(changed.target.value)
                          }
                          className="w-full rounded-[var(--radius-sm)] border border-border bg-surface px-[var(--space-2)] py-[var(--space-1)] text-sm"
                        />
                      </form>
                    ) : (
                      <div className="group flex items-center gap-[var(--space-1)]">
                        <button
                          type="button"
                          aria-current={
                            conversationId === item.conversation_id
                              ? "page"
                              : undefined
                          }
                          onClick={() =>
                            navigate(`/conversations/${item.conversation_id}`)
                          }
                          className="min-w-0 flex-1 truncate rounded-[var(--radius-sm)] px-[var(--space-2)] py-[var(--space-1)] text-left text-sm hover:bg-surface-sunken aria-[current=page]:bg-surface-sunken aria-[current=page]:font-medium"
                        >
                          {item.title}
                        </button>
                        <button
                          type="button"
                          aria-label={`Rename ${item.title}`}
                          onClick={() => {
                            setRenaming(item.conversation_id);
                            setDraftTitle(item.title);
                          }}
                          className="px-[var(--space-1)] text-xs text-text-muted"
                        >
                          Rename
                        </button>
                        <button
                          type="button"
                          aria-label={`Archive ${item.title}`}
                          onClick={() => archive.mutate(item.conversation_id)}
                          className="px-[var(--space-1)] text-xs text-text-muted"
                        >
                          Archive
                        </button>
                        <button
                          type="button"
                          aria-label={`Delete ${item.title}`}
                          onClick={() => {
                            // Deletion is recoverable, and saying so is what
                            // makes the confirmation honest rather than scary.
                            const confirmed = window.confirm(
                              `Delete "${item.title}"? It is removed from your history and can be recovered until retention is configured.`,
                            );
                            if (confirmed) remove.mutate(item.conversation_id);
                          }}
                          className="px-[var(--space-1)] text-xs text-danger"
                        >
                          Delete
                        </button>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
