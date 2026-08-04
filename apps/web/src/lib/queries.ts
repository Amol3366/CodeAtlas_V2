import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./api";

/**
 * Server state, keyed so an update invalidates exactly what it changed.
 *
 * The server is the source of truth for everything here (`AGENTS.md`
 * Section 14.5); these hooks cache it, never replace it.
 */

export interface Repository {
  readonly repository_id: string;
  readonly display_name: string;
  readonly created_at: string;
}

export interface SnapshotRef {
  readonly snapshot_id: string | null;
  readonly git_head: string | null;
  readonly working_tree_fingerprint: string | null;
  readonly freshness: string;
  readonly semantic_coverage: number;
}

export interface RepositoryStatus {
  readonly repository_id: string;
  readonly snapshot: SnapshotRef | null;
  readonly file_count: number;
  readonly symbol_count: number;
  readonly parse_error_count: number;
  readonly warnings: readonly string[];
}

export interface Diagnostics {
  readonly repository_id: string;
  readonly snapshot_id: string | null;
  readonly parse_error_count: number;
  readonly skipped_by_reason: Readonly<Record<string, number>>;
  readonly limits: Readonly<Record<string, number>>;
  readonly warnings: readonly string[];
}

export const keys = {
  repositories: ["repositories"] as const,
  status: (id: string) => ["repositories", id, "status"] as const,
  diagnostics: (id: string) => ["repositories", id, "diagnostics"] as const,
  conversations: (repositoryId: string) =>
    ["conversations", repositoryId] as const,
  messages: (conversationId: string) =>
    ["conversations", conversationId, "messages"] as const,
};

export function useRepositories() {
  return useQuery({
    queryKey: keys.repositories,
    queryFn: () => api.get<Repository[]>("/v1/repositories"),
  });
}

export function useAddRepository() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (path: string) =>
      api.post<Repository>("/v1/repositories", { path }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.repositories }),
  });
}

/**
 * Status, polled only while indexing is genuinely in progress.
 *
 * Polling a terminal state forever would be a request the user is paying for
 * that can never change its answer.
 */
export function useRepositoryStatus(repositoryId: string | null) {
  return useQuery({
    queryKey: keys.status(repositoryId ?? ""),
    queryFn: () =>
      api.get<RepositoryStatus>(`/v1/repositories/${repositoryId}/status`),
    enabled: repositoryId !== null,
    refetchInterval: (query) => {
      const state = query.state.data?.snapshot?.freshness;
      const settled =
        state === undefined || state === "fresh" || state === "stale";
      return settled ? false : 1500;
    },
  });
}

export function useIndexRepository() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (repositoryId: string) =>
      api.post<{ state: string; snapshot_id: string }>(
        `/v1/repositories/${repositoryId}/index`,
      ),
    onSuccess: (_data, repositoryId) => {
      void client.invalidateQueries({ queryKey: keys.status(repositoryId) });
      void client.invalidateQueries({
        queryKey: keys.diagnostics(repositoryId),
      });
    },
  });
}

export function useDiagnostics(repositoryId: string | null) {
  return useQuery({
    queryKey: keys.diagnostics(repositoryId ?? ""),
    queryFn: () =>
      api.get<Diagnostics>(`/v1/repositories/${repositoryId}/diagnostics`),
    enabled: repositoryId !== null,
  });
}

export interface RepositorySettings {
  readonly repository_id: string;
  readonly embedding_provider: string;
  readonly monthly_token_budget: number | null;
  readonly per_run_token_budget: number | null;
  readonly transmits_off_machine: boolean;
  readonly updated_at: string;
  readonly answer_provider: string;
  readonly answer_model: string | null;
  readonly answer_timeout_seconds: number | null;
  /** Null means "use the configured default for the chosen provider". */
  readonly embedding_model: string | null;
}

export interface EmbeddingModel {
  readonly provider: string;
  readonly model_id: string | null;
  readonly dimensions: number | null;
  readonly available: boolean;
  readonly transmits_off_machine: boolean;
  readonly requires: string | null;
}

/** An answer provider. No `dimensions`: an answer model has none. */
export interface AnswerModel {
  readonly provider: string;
  readonly model_id: string | null;
  readonly available: boolean;
  readonly transmits_off_machine: boolean;
  readonly requires: string | null;
}

export interface SemanticStatus {
  readonly repository_id: string;
  readonly provider: string;
  readonly enabled: boolean;
  readonly snapshot_id: string | null;
  readonly coverage: number | null;
  readonly total_count: number | null;
  readonly embedded_count: number | null;
  readonly pending_count: number | null;
  readonly failed_count: number | null;
  readonly namespace_id: string | null;
  readonly model_id: string | null;
  readonly is_complete: boolean;
}

export interface ProviderTest {
  readonly provider: string;
  readonly ok: boolean;
  readonly detail_code: string | null;
  readonly latency_ms: number;
}

export interface OllamaModelPull {
  readonly provider: "ollama";
  readonly model_id: string;
  readonly ok: boolean;
  readonly detail_code: string | null;
  readonly latency_ms: number;
}

export interface SettingsUpdate {
  readonly embedding_provider?: string;
  readonly monthly_token_budget?: number | null;
  readonly per_run_token_budget?: number | null;
  readonly answer_provider?: string;
  readonly answer_model?: string | null;
  readonly answer_timeout_seconds?: number | null;
  readonly embedding_model?: string | null;
}

export function useSettings(repositoryId: string | null) {
  return useQuery({
    queryKey: ["settings", repositoryId] as const,
    queryFn: () =>
      api.get<RepositorySettings>(
        `/v1/settings?repository_id=${encodeURIComponent(repositoryId!)}`,
      ),
    enabled: repositoryId !== null,
    refetchOnMount: "always",
  });
}

export function useModels() {
  return useQuery({
    queryKey: ["models"] as const,
    // The list is a property of the installation, not of a repository, so it
    // is fetched once rather than per selected repository.
    queryFn: () =>
      api.get<{
        models: EmbeddingModel[];
        // Optional so a response from a backend older than answer generation
        // still parses rather than crashing the settings page.
        answer_models?: AnswerModel[];
      }>("/v1/models"),
    refetchOnMount: "always",
  });
}

export function useSemanticStatus(repositoryId: string | null) {
  return useQuery({
    queryKey: ["semantic-status", repositoryId] as const,
    queryFn: () =>
      api.get<SemanticStatus>(
        `/v1/repositories/${encodeURIComponent(repositoryId!)}/semantic-status`,
      ),
    enabled: repositoryId !== null,
    refetchOnMount: "always",
  });
}

export function useUpdateSettings(repositoryId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (update: SettingsUpdate) =>
      api.patch<RepositorySettings>(
        `/v1/settings?repository_id=${encodeURIComponent(repositoryId)}`,
        update,
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["settings", repositoryId] });
      // Coverage depends on which provider is selected, so it is stale the
      // moment the provider changes.
      void client.invalidateQueries({
        queryKey: ["semantic-status", repositoryId],
      });
    },
  });
}

export function useTestProvider(repositoryId: string) {
  return useMutation({
    mutationFn: () =>
      api.post<ProviderTest>(
        `/v1/models/test?repository_id=${encodeURIComponent(repositoryId)}`,
      ),
  });
}

/** The measured result of loading a candidate local embedding model. */
export interface EmbeddingModelValidation {
  readonly provider: "local";
  readonly model_id: string;
  readonly ok: boolean;
  /** Measured by loading the model. Null when it could not be loaded. */
  readonly dimensions: number | null;
  readonly detail_code: string | null;
  readonly latency_ms: number;
}

export function useValidateEmbeddingModel() {
  return useMutation({
    mutationFn: (modelId: string) =>
      api.post<EmbeddingModelValidation>("/v1/models/embedding/validate", {
        model_id: modelId,
      }),
  });
}

export function usePullOllamaModel() {
  return useMutation({
    mutationFn: (modelId: string) =>
      api.post<OllamaModelPull>("/v1/models/ollama/pull", {
        model_id: modelId,
      }),
  });
}
