import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";

import { useActiveRepository } from "../app/context";
import { Skeleton } from "../components/Skeleton";
import {
  useConversations,
  useCreateConversation,
} from "../lib/conversations";
import { useRepositoryStatus } from "../lib/queries";
import { ErrorNotice } from "../features/repositories/RepositoryPanel";

/**
 * Chat entry route.
 *
 * Opening the app should land in conversation space. Repository registration
 * and indexing are still reachable, but they are deliberate actions on
 * `/repositories`, not the first thing the app tries to do.
 */
export function HomeRoute() {
  const { repositoryId } = useActiveRepository();
  const navigate = useNavigate();
  const status = useRepositoryStatus(repositoryId);
  const conversations = useConversations(repositoryId);
  const create = useCreateConversation(repositoryId);
  const {
    error: createError,
    isError: createIsError,
    isPending: createIsPending,
    mutate: createConversation,
  } = create;
  const creatingFor = useRef<string | null>(null);

  const activeSnapshotId = status.data?.snapshot?.snapshot_id ?? null;
  const firstConversation = conversations.data?.items[0] ?? null;

  useEffect(() => {
    if (repositoryId === null || activeSnapshotId === null) return;
    if (conversations.isPending || conversations.isError) return;
    if (firstConversation !== null) return;
    if (createIsPending || createIsError || creatingFor.current === repositoryId) {
      return;
    }

    creatingFor.current = repositoryId;
    createConversation(undefined, {
      onSuccess: (created) =>
        navigate(`/conversations/${created.conversation_id}`, {
          replace: true,
        }),
      onError: () => {
        creatingFor.current = null;
      },
    });
  }, [
    activeSnapshotId,
    conversations.isError,
    conversations.isPending,
    createConversation,
    createIsError,
    createIsPending,
    firstConversation,
    navigate,
    repositoryId,
  ]);

  if (repositoryId === null) {
    return (
      <ChatGate
        title="No repository selected"
        body="Add or select a local repository before starting a chat."
      />
    );
  }

  if (status.isPending || conversations.isPending) {
    return (
      <div className="mx-auto flex h-full max-w-[var(--measure)] flex-col p-[var(--space-6)]">
        <Skeleton className="h-40 w-full" label="Opening chat" />
      </div>
    );
  }

  if (status.isError) {
    return (
      <ChatGate title="Chat is unavailable" body="Repository status could not be read.">
        <ErrorNotice error={status.error} />
      </ChatGate>
    );
  }

  if (activeSnapshotId === null) {
    return (
      <ChatGate
        title="Index this repository"
        body="Chat needs an active index before it can answer from this directory."
      />
    );
  }

  if (conversations.isError) {
    return (
      <ChatGate title="Chat is unavailable" body="Conversations could not be read.">
        <ErrorNotice error={conversations.error} />
      </ChatGate>
    );
  }

  if (firstConversation !== null) {
    return (
      <Navigate
        to={`/conversations/${firstConversation.conversation_id}`}
        replace
      />
    );
  }

  return (
    <ChatGate title="Opening chat" body="Preparing a new conversation.">
      {createIsError ? <ErrorNotice error={createError} /> : null}
    </ChatGate>
  );
}

function ChatGate({
  title,
  body,
  children,
}: {
  readonly title: string;
  readonly body: string;
  readonly children?: ReactNode;
}) {
  return (
    <div className="mx-auto flex h-full max-w-[var(--measure)] flex-col justify-center p-[var(--space-6)]">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-[var(--space-2)] text-sm text-text-muted">{body}</p>
        <Link
          to="/repositories"
          className="mt-[var(--space-4)] inline-flex rounded-[var(--radius-md)] border border-border px-[var(--space-3)] py-[var(--space-2)] text-sm font-medium hover:bg-surface-sunken"
        >
          Repositories
        </Link>
        {children}
      </div>
    </div>
  );
}
