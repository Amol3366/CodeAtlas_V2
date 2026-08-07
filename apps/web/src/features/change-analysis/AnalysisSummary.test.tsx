import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AnalysisSummary } from "./AnalysisSummary";
import type { ChangeReport } from "./useAnalysis";

function report(overrides: Partial<ChangeReport> = {}): ChangeReport {
  return {
    analysis_id: "a1",
    repository_id: "r1",
    request_id: "q1",
    contract_version: "1.1",
    created_at: "2026-08-07T00:00:00Z",
    kind: "working_tree",
    status: "complete",
    overall_risk: "high",
    base: {
      ref: "HEAD",
      commit: "abc1234",
      freshness: "fresh",
      snapshot_id: null,
    },
    target: {
      ref: "working-tree",
      commit: null,
      freshness: "fresh",
      snapshot_id: null,
    },
    ...overrides,
  } as ChangeReport;
}

describe("AnalysisSummary", () => {
  it("states the risk as a word, not only a colour", () => {
    render(<AnalysisSummary report={report()} />);

    expect(screen.getByTestId("overall-risk")).toHaveTextContent("high");
  });

  it("shows both refs with their freshness", () => {
    render(<AnalysisSummary report={report()} />);

    expect(screen.getByText("HEAD")).toBeInTheDocument();
    expect(screen.getAllByText(/fresh/).length).toBeGreaterThan(0);
  });

  it("counts an absent array as zero rather than crashing", () => {
    // Every array on the report is optional in the generated contract.
    render(<AnalysisSummary report={report()} />);

    expect(screen.getByText(/0 findings/)).toBeInTheDocument();
  });

  it("counts what the report actually carries", () => {
    const withCounts = report({
      changed_symbols: [{}, {}],
      test_gaps: ["orders.Order"],
    } as Partial<ChangeReport>);

    render(<AnalysisSummary report={withCounts} />);

    expect(screen.getByText(/2 symbols/)).toBeInTheDocument();
    expect(screen.getByText(/1 possible test gap/)).toBeInTheDocument();
  });
});
