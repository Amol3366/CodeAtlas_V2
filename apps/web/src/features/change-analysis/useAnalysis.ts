import { useMutation, useQuery } from "@tanstack/react-query";

import { api } from "../../lib/api";
import type { components } from "../../lib/api-types.gen";

/**
 * Server state for change analysis.
 *
 * Every type here aliases the generated contract rather than restating it. The
 * screen this feeds previously hand-wrote its own `ChangeReport` interface,
 * which is how a frontend drifts from a contract it is supposed to consume:
 * nothing fails when the backend adds a field, and nothing fails when it
 * removes one.
 */

export type ChangeReport = components["schemas"]["ChangeAnalysisReport"];
export type Finding = components["schemas"]["Finding"];
export type ChangedSymbol = components["schemas"]["ChangedSymbol"];
export type ChangedFile = components["schemas"]["ChangedFile"];
export type ImpactEdge = components["schemas"]["ImpactEdge"];
export type GapReason = components["schemas"]["GapReason"];
export type ChangeEvidenceItem = components["schemas"]["ChangeEvidenceItem"];
export type AnalysisStateRef = components["schemas"]["AnalysisStateRef"];

export function evidenceById(
  report: ChangeReport,
): Map<string, ChangeEvidenceItem> {
  return new Map(
    (report.evidence ?? []).map((item) => [item.evidence_id, item]),
  );
}

export function useAnalysis(analysisId: string | undefined) {
  return useQuery({
    queryKey: ["change-analysis", analysisId ?? ""],
    queryFn: () =>
      api.get<ChangeReport>(
        `/v1/change-analysis/${encodeURIComponent(analysisId ?? "")}`,
      ),
    enabled: analysisId !== undefined && analysisId !== "",
    // A persisted analysis is an audit record: it cannot change under us, so
    // refetching it would spend a request to receive the same bytes.
    staleTime: Infinity,
    retry: false,
  });
}

export function useRunWorkingTree() {
  return useMutation({
    mutationFn: (input: { repositoryId: string; baseRef: string }) =>
      api.post<ChangeReport>("/v1/change-analysis/working-tree", {
        repository_id: input.repositoryId,
        base_ref: input.baseRef,
      }),
  });
}

export function useRunCommitRange() {
  return useMutation({
    mutationFn: (input: {
      repositoryId: string;
      baseRef: string;
      targetRef: string;
    }) =>
      api.post<ChangeReport>("/v1/change-analysis/commits", {
        repository_id: input.repositoryId,
        base_ref: input.baseRef,
        target_ref: input.targetRef,
      }),
  });
}
