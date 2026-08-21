import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./api";
import { keys } from "./queries";

export interface Conversation {
  readonly conversation_id: string;
  readonly repository_id: string;
  readonly title: string;
  readonly created_at: string;
  readonly updated_at: string;
  readonly last_message_at: string | null;
  readonly archived_at: string | null;
}

export interface ConversationPage {
  readonly items: readonly Conversation[];
  readonly next_cursor: string | null;
}

export interface MessageEvidence {
  readonly evidence_id: string;
  readonly citation_ordinal: number;
  readonly file_path: string;
  readonly symbol: string | null;
  readonly start_line: number;
  readonly end_line: number;
  readonly content_hash: string;
  readonly derivation: string;
  readonly confidence: number;
  readonly snapshot_id: string;
}

export interface Message {
  readonly message_id: string;
  readonly conversation_id: string;
  readonly role: "user" | "assistant" | "system_event";
  readonly status:
    | "queued"
    | "retrieving"
    | "generating"
    | "complete"
    | "failed"
    | "cancelled";
  readonly sequence_number: number;
  readonly content: string;
  readonly error_code: string | null;
  readonly created_at: string;
  readonly completed_at: string | null;
  /**
   * Carried with the message since P6-STREAM (ADR-0008).
   *
   * The submission response no longer contains the answer, so these are the
   * only source for what a reopened thread shows: what the answer cited, which
   * snapshot it examined, and what it warned about. Holding them in component
   * state instead would lose all three on reload.
   */
  readonly evidence: readonly MessageEvidence[];
  readonly snapshot_id: string | null;
  readonly warnings: readonly string[];
}

export interface MessagePage {
  readonly items: readonly Message[];
  readonly next_cursor: string | null;
}


export interface MessageSubmission {
  readonly conversation_id: string;
  readonly user_message_id: string;
  readonly message_id: string;
  readonly run_id: string;
  readonly status: Message["status"];
  readonly sequence_number: number;
  readonly content: string;
  readonly snapshot_id: string | null;
  readonly intent: string;
  readonly evidence: readonly MessageEvidence[];
  readonly warnings: readonly string[];
  readonly limitations: readonly string[];
  readonly error_code: string | null;
  readonly latency_ms: number | null;
}

export function useConversations(repositoryId: string | null) {
  return useQuery({
    queryKey: keys.conversations(repositoryId ?? ""),
    queryFn: () =>
      api.get<ConversationPage>(
        `/v1/conversations?repository_id=${encodeURIComponent(repositoryId ?? "")}`,
      ),
    enabled: repositoryId !== null && repositoryId !== "",
  });
}

export function useCreateConversation(repositoryId: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post<Conversation>("/v1/conversations", {
        repository_id: repositoryId,
      }),
    onSuccess: () =>
      client.invalidateQueries({
        queryKey: keys.conversations(repositoryId ?? ""),
      }),
  });
}

export function useRenameConversation(repositoryId: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      api.patch<Conversation>(`/v1/conversations/${id}`, { title }),
    onSuccess: () =>
      client.invalidateQueries({
        queryKey: keys.conversations(repositoryId ?? ""),
      }),
  });
}

export function useArchiveConversation(repositoryId: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api.patch<Conversation>(`/v1/conversations/${id}`, { archived: true }),
    onSuccess: () =>
      client.invalidateQueries({
        queryKey: keys.conversations(repositoryId ?? ""),
      }),
  });
}

export function useDeleteConversation(repositoryId: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/v1/conversations/${id}`),
    onSuccess: () =>
      client.invalidateQueries({
        queryKey: keys.conversations(repositoryId ?? ""),
      }),
  });
}

export function useMessages(conversationId: string | null) {
  return useQuery({
    queryKey: keys.messages(conversationId ?? ""),
    queryFn: () =>
      api.get<MessagePage>(`/v1/conversations/${conversationId}/messages`),
    enabled: conversationId !== null && conversationId !== "",
  });
}

export function useSubmitMessage(conversationId: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (content: string) =>
      api.post<MessageSubmission>(
        `/v1/conversations/${conversationId}/messages`,
        { content },
      ),
    onSuccess: () => {
      // The persisted messages are authoritative; refetch rather than patching
      // the cache from the submission response.
      void client.invalidateQueries({
        queryKey: keys.messages(conversationId ?? ""),
      });
      void client.invalidateQueries({ queryKey: ["conversations"] });
    },
  });
}

export function useRetryMessage(conversationId: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (messageId: string) =>
      api.post<MessageSubmission>(`/v1/messages/${messageId}/retry`),
    onSuccess: () =>
      client.invalidateQueries({
        queryKey: keys.messages(conversationId ?? ""),
      }),
  });
}

/**
 * Groups conversations the way a reader thinks about them.
 *
 * The ordering comes from the backend; this only labels the boundaries, using
 * the backend's own timestamps so a client clock cannot reorder history.
 */
export function groupByRecency(
  conversations: readonly Conversation[],
  now: Date = new Date(),
): ReadonlyArray<readonly [string, readonly Conversation[]]> {
  const groups = new Map<string, Conversation[]>();
  const startOfToday = new Date(now);
  startOfToday.setHours(0, 0, 0, 0);

  for (const conversation of conversations) {
    const at = new Date(conversation.last_message_at ?? conversation.created_at);
    const days = Math.floor(
      (startOfToday.getTime() - at.getTime()) / 86_400_000,
    );
    const label =
      at.getTime() >= startOfToday.getTime()
        ? "Today"
        : days < 1
          ? "Yesterday"
          : days < 7
            ? "Previous 7 days"
            : days < 30
              ? "Previous 30 days"
              : "Older";
    const bucket = groups.get(label) ?? [];
    bucket.push(conversation);
    groups.set(label, bucket);
  }

  const order = ["Today", "Yesterday", "Previous 7 days", "Previous 30 days", "Older"];
  return order
    .filter((label) => groups.has(label))
    .map((label) => [label, groups.get(label) ?? []] as const);
}
