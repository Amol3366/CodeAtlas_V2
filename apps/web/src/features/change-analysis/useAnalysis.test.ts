import { describe, expect, it } from "vitest";

import { evidenceById } from "./useAnalysis";
import type { ChangeEvidenceItem, ChangeReport } from "./useAnalysis";

function report(overrides: Partial<ChangeReport> = {}): ChangeReport {
  return {
    analysis_id: "a1",
    repository_id: "r1",
    request_id: "q1",
    contract_version: "1.1",
    created_at: "2026-08-07T00:00:00Z",
    kind: "working_tree",
    status: "complete",
    overall_risk: "low",
    base: { ref: "HEAD", commit: "abc", freshness: "fresh", snapshot_id: null },
    target: {
      ref: "working-tree",
      commit: null,
      freshness: "fresh",
      snapshot_id: null,
    },
    ...overrides,
  } as ChangeReport;
}

describe("evidenceById", () => {
  it("indexes evidence so a finding can resolve its citations", () => {
    const item = {
      evidence_id: "e1",
      side: "target",
      file_path: "src/orders.py",
      start_line: 1,
      end_line: 2,
      content_hash: "h",
      derivation: "deterministic",
      confidence: 1,
    } as ChangeEvidenceItem;

    const map = evidenceById(report({ evidence: [item] }));

    expect(map.get("e1")?.file_path).toBe("src/orders.py");
  });

  it("returns an empty map when the report carries no evidence", () => {
    // Every array on ChangeAnalysisReport is optional in the generated types.
    // A consumer that assumes an array crashes on a report without one.
    expect(evidenceById(report()).size).toBe(0);
  });
});
