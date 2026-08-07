import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { apiError, renderWithProviders, stubFetch } from "../test/harness";
import { PreflightAnalysisRoute } from "./PreflightAnalysisRoute";

function renderAnalysis(analysisId: string) {
  return renderWithProviders(<PreflightAnalysisRoute />, {
    route: `/preflight/${analysisId}`,
    path: "/preflight/:analysisId",
  });
}

function report(overrides: Record<string, unknown> = {}) {
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
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("PreflightAnalysisRoute", () => {
  it("renders a persisted analysis loaded by id", async () => {
    stubFetch({ "/v1/change-analysis/a1": { body: report({ findings: [] }) } });

    renderAnalysis("a1");

    expect(await screen.findByTestId("overall-risk")).toHaveTextContent("high");
  });

  it("renders a report whose arrays are entirely absent", async () => {
    // Every array on ChangeAnalysisReport is optional in the generated
    // contract. A route that assumes one crashes on a minimal report.
    stubFetch({
      "/v1/change-analysis/a1": { body: report({ overall_risk: "low" }) },
    });

    renderAnalysis("a1");

    expect(await screen.findByTestId("overall-risk")).toHaveTextContent("low");
  });

  it("shows the test gaps and their reasons", async () => {
    stubFetch({
      "/v1/change-analysis/a1": {
        body: report({
          test_gaps: ["orders.Order"],
          test_gap_reasons: [
            {
              qualified_name: "orders.Order",
              reason: "FIXTURE_MEDIATED_ONLY",
              explanation: "A test reaches this only through a fixture.",
              evidence_ids: [],
            },
          ],
        }),
      },
    });

    renderAnalysis("a1");

    expect(await screen.findByText("orders.Order")).toBeInTheDocument();
    expect(screen.getByText("FIXTURE_MEDIATED_ONLY")).toBeInTheDocument();
    expect(
      screen.getByText(/does not prove absence of coverage/i),
    ).toBeInTheDocument();
  });

  it("shows a not-found message and a way back for an unknown id", async () => {
    stubFetch({
      "/v1/change-analysis/missing": {
        status: 404,
        body: apiError("CHANGE_ANALYSIS_NOT_FOUND", "No such analysis."),
      },
    });

    renderAnalysis("missing");

    expect(
      await screen.findByText(/analysis was not found/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /run a preflight/i }),
    ).toHaveAttribute("href", "/preflight");
  });
});
