import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { Markdown } from "../../components/Markdown";
import { Skeleton } from "../../components/Skeleton";
import type { Message, MessageEvidence } from "../../lib/conversations";
import {
  useMessages,
  useRetryMessage,
  useSubmitMessage,
} from "../../lib/conversations";
import { keys } from "../../lib/queries";
import type { StreamSubscription } from "../../lib/sse";
import { subscribeToConversation } from "../../lib/sse";
import { ErrorNotice } from "../repositories/RepositoryPanel";

/**
 * One conversation thread.
 *
 * Section 14.5's rules, made concrete:
 *
 * - the submitted question appears immediately, keyed locally, and is replaced
 *   by the server's row when it arrives — reconciled by ID, never duplicated;
 * - assistant text renders only through the sanitizer;
 * - a message whose run answered against a superseded snapshot says so, and
 *   keeps its own label rather than borrowing the current one;
 * - switching threads discards the pending state of the previous one, so
 *   nothing can leak across.
 */

export interface ThreadProps {
  readonly conversationId: string;
  readonly activeSnapshotId?: string | null | undefined;
  readonly onCite?: ((evidence: MessageEvidence, messageId: string) => void) | undefined;
}

interface PendingTurn {
  readonly key: string;
  readonly content: string;
}

function StatusLine({ status }: { readonly status: Message["status"] }) {
  // The stage names come from the pipeline's own vocabulary rather than a
  // decorative spinner caption: "Resolving symbols" is a claim about what the
  // server is doing, so it must be one the server actually made.
  const label =
    status === "queued"
      ? "Queued"
      : status === "retrieving"
        ? "Resolving symbols and relations…"
        : status === "generating"
          ? "Composing the answer…"
          : null;
  if (label === null) return null;
  return (
    <p role="status" className="text-sm text-text-muted">
      {label}
    </p>
  );
}

function AssistantTurn({
  message,
  evidence,
  snapshotId,
  activeSnapshotId,
  onRetry,
  retrying,
  onCite,
  streamed,
}: {
  readonly message: Message;
  readonly evidence: readonly MessageEvidence[];
  readonly snapshotId: string | null;
  readonly activeSnapshotId?: string | null | undefined;
  readonly onRetry: () => void;
  readonly retrying: boolean;
  readonly onCite?: ((evidence: MessageEvidence, messageId: string) => void) | undefined;
  /**
   * Text accumulated from `generation.delta` while this run is live.
   *
   * Provisional by contract (Section 11.2): it is shown while the run is in
   * flight and dropped the moment the persisted answer arrives, which is the
   * authoritative one.
   */
  readonly streamed?: string | null | undefined;
}) {
  // Streamed text wins only while it exists; the persisted answer replaces it.
  const visible =
    streamed !== null && streamed !== undefined && streamed !== ""
      ? streamed
      : message.content;
  const stale =
    snapshotId !== null &&
    activeSnapshotId !== undefined &&
    activeSnapshotId !== null &&
    snapshotId !== activeSnapshotId;

  if (message.status === "failed" || message.status === "cancelled") {
    return (
      <div className="rounded-[var(--radius-md)] border border-border p-[var(--space-4)]">
        <p role="alert" className="text-sm">
          {message.status === "failed"
            ? "This answer failed."
            : "This answer was cancelled."}{" "}
          {message.error_code !== null ? (
            <code className="text-text-muted">{message.error_code}</code>
          ) : null}
        </p>
        <button
          type="button"
          onClick={onRetry}
          disabled={retrying}
          className="mt-[var(--space-2)] rounded-[var(--radius-md)] border border-border px-[var(--space-3)] py-[var(--space-1)] text-sm disabled:opacity-50"
        >
          {retrying ? "Retrying…" : "Retry"}
        </button>
      </div>
    );
  }

  return (
    <div>
      {stale ? (
        <p
          data-testid="freshness-banner"
          className="mb-[var(--space-2)] rounded-[var(--radius-sm)] border border-border px-[var(--space-2)] py-[var(--space-1)] text-xs text-stale"
        >
          Answered against an earlier snapshot ({snapshotId}). The repository has
          been re-indexed since.
        </p>
      ) : null}
      <StatusLine status={message.status} />
      {message.warnings.length > 0 ? (
        <ul
          data-testid="run-warnings"
          className="mb-[var(--space-2)] space-y-[var(--space-1)]"
        >
          {message.warnings.map((warning) => (
            <li key={warning} className="text-xs text-stale">
              {warning}
            </li>
          ))}
        </ul>
      ) : null}
      <Markdown>{visible}</Markdown>
      {evidence.length > 0 ? (
        <ul className="mt-[var(--space-3)] flex flex-wrap gap-[var(--space-2)]">
          {evidence.map((item) => (
            <li key={item.evidence_id}>
              <button
                type="button"
                onClick={() => onCite?.(item, message.message_id)}
                className="rounded-[var(--radius-sm)] border border-border px-[var(--space-2)] py-[var(--space-1)] text-xs"
              >
                [{item.citation_ordinal}] {item.file_path}:{item.start_line}-
                {item.end_line}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function Thread({
  conversationId,
  activeSnapshotId,
  onCite,
}: ThreadProps) {
  const messages = useMessages(conversationId);
  const submit = useSubmitMessage(conversationId);
  const retry = useRetryMessage(conversationId);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState<PendingTurn | null>(null);
  const [streamedByMessage, setStreamedByMessage] = useState<
    Record<string, string>
  >({});
  const composer = useRef<HTMLTextAreaElement>(null);
  const subscription = useRef<StreamSubscription | null>(null);
  const client = useQueryClient();

  const stopStreaming = () => {
    subscription.current?.close();
    subscription.current = null;
  };

  // Switching threads must not carry the previous thread's pending turn or its
  // streamed text across, and must not leave its stream open — a live
  // subscription would keep appending another conversation's deltas into this
  // one (Section 14.5).
  useEffect(() => {
    stopStreaming();
    setPending(null);
    setStreamedByMessage({});
    setDraft("");
  }, [conversationId]);

  // Closing the stream on unmount is not tidiness: an EventSource outlives the
  // component that opened it and would hold a connection open for a thread
  // nobody is looking at.
  useEffect(() => stopStreaming, []);

  /**
   * Follow one accepted run to its end.
   *
   * The stream is opened *after* the 202, which is safe because the server
   * opens the run's channel before answering (ADR-0008) — there is no window in
   * which the run exists and the stream does not. Streamed text is provisional;
   * when the run terminates the persisted message is refetched and becomes what
   * is shown.
   */
  const follow = (messageId: string) => {
    stopStreaming();
    const readPersisted = () => {
      void client.invalidateQueries({ queryKey: keys.messages(conversationId) });
    };
    try {
      subscription.current = openStream(messageId, readPersisted);
    } catch {
      // The live view is an optimisation, never the answer. If the stream
      // cannot be opened at all — no EventSource, a blocked connection — the
      // turn is still accepted and its answer is still persisted, so fall back
      // to reading it. Letting this throw would reject inside the submission's
      // success callback and lose an answer that already exists.
      subscription.current = null;
      readPersisted();
    }
  };

  const openStream = (messageId: string, onFinished: () => void) => {
    return subscribeToConversation(conversationId, {
      onEvent: (event) => {
        if (event.event === "generation.delta") {
          const delta = event.payload["text"];
          if (typeof delta === "string") {
            setStreamedByMessage((current) => ({
              ...current,
              [messageId]: (current[messageId] ?? "") + delta,
            }));
          }
        }
      },
      onClose: () => {
        subscription.current = null;
        // Whatever happened — completed, failed, cancelled, or a dropped
        // connection — the persisted message is the authority, so read it.
        onFinished();
        setStreamedByMessage((current) => {
          if (!(messageId in current)) return current;
          const rest = { ...current };
          delete rest[messageId];
          return rest;
        });
      },
    });
  };

  const send = () => {
    const question = draft.trim();
    if (question === "" || submit.isPending) return;
    setPending({ key: `pending-${Date.now()}`, content: question });
    setDraft("");
    submit.mutate(question, {
      onSuccess: (result) => {
        // The turn is committed and the run is queued; the local placeholder
        // has served its purpose and is dropped rather than merged.
        setPending(null);
        follow(result.message_id);
      },
      onError: () => setPending(null),
    });
  };

  if (messages.isPending) {
    return <Skeleton className="h-40 w-full" label="Loading messages" />;
  }
  if (messages.isError) return <ErrorNotice error={messages.error} />;

  return (
    <div className="flex h-full flex-col">
      <ol className="min-h-0 flex-1 space-y-[var(--space-6)] overflow-y-auto">
        {messages.data.items.map((message) => (
          <li key={message.message_id} data-testid={`message-${message.role}`}>
            {message.role === "user" ? (
              <p className="rounded-[var(--radius-md)] bg-surface-sunken p-[var(--space-3)]">
                {message.content}
              </p>
            ) : (
              <AssistantTurn
                message={message}
                // From the message, not from component state: a reload has no
                // submission response to remember (ADR-0008).
                evidence={message.evidence}
                snapshotId={message.snapshot_id}
                streamed={streamedByMessage[message.message_id] ?? null}
                activeSnapshotId={activeSnapshotId}
                retrying={retry.isPending}
                onRetry={() => retry.mutate(message.message_id)}
                {...(onCite ? { onCite } : {})}
              />
            )}
          </li>
        ))}
        {pending !== null ? (
          <li key={pending.key} data-testid="pending-turn">
            <p className="rounded-[var(--radius-md)] bg-surface-sunken p-[var(--space-3)] opacity-70">
              {pending.content}
            </p>
            <p role="status" className="mt-[var(--space-2)] text-sm text-text-muted">
              Sending…
            </p>
          </li>
        ) : null}
      </ol>

      {submit.isError ? <ErrorNotice error={submit.error} /> : null}

      <form
        className="mt-[var(--space-4)] border-t border-border pt-[var(--space-3)]"
        onSubmit={(submitted) => {
          submitted.preventDefault();
          send();
        }}
      >
        <label htmlFor="composer" className="sr-only">
          Ask about this repository
        </label>
        <textarea
          id="composer"
          ref={composer}
          rows={3}
          value={draft}
          placeholder="Ask about this repository"
          onChange={(changed) => setDraft(changed.target.value)}
          onKeyDown={(pressed) => {
            // Enter sends, Shift+Enter is a newline: the convention every chat
            // surface uses, so breaking it would surprise everyone.
            if (pressed.key === "Enter" && !pressed.shiftKey) {
              pressed.preventDefault();
              send();
            }
          }}
          className="w-full resize-y rounded-[var(--radius-md)] border border-border bg-surface p-[var(--space-3)]"
        />
        <div className="mt-[var(--space-2)] flex justify-end">
          <button
            type="submit"
            disabled={submit.isPending || draft.trim() === ""}
            className="rounded-[var(--radius-md)] bg-accent px-[var(--space-4)] py-[var(--space-2)] text-sm font-medium text-accent-contrast disabled:opacity-50"
          >
            {submit.isPending ? "Answering…" : "Send"}
          </button>
        </div>
      </form>
    </div>
  );
}
