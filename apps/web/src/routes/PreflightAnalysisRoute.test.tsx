import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

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

  it("has no accessibility violations with a fully populated report", async () => {
    stubFetch({
      "/v1/change-analysis/a1": {
        body: report({
          findings: [
            {
              code: "PUBLIC_CONTRACT_CHANGED",
              severity: "high",
              title: "Public contract changed",
              description: "The signature changed.",
              derivation: "static_resolved",
              confidence: 0.9,
              evidence_ids: ["e1"],
              limitations: [],
            },
            {
              code: "DOC_MAY_BE_STALE",
              severity: "low",
              title: "A document may be stale",
              description: "A document references the changed symbol.",
              derivation: "low_confidence_heuristic",
              confidence: 0.3,
              evidence_ids: [],
              limitations: [],
            },
          ],
          changed_symbols: [
            {
              qualified_name: "orders.Order.total",
              symbol_kind: "METHOD",
              change_kind: "modified",
              file_path: "src/orders.py",
              target_start_line: 40,
              target_end_line: 52,
              confidence: 1,
              derivation: "deterministic",
              public: true,
              signature_changed: true,
            },
          ],
          changed_files: [
            {
              path: "pyproject.toml",
              change_kind: "modified",
              content_hash_changed: true,
            },
          ],
          impact_edges: [
            {
              source: "orders.Order.total",
              kind: "CALLS",
              target: "api.checkout",
              derivation: "static_resolved",
              confidence: 0.9,
            },
          ],
          test_gaps: ["orders.Order"],
          test_gap_reasons: [
            {
              qualified_name: "orders.Order",
              reason: "FIXTURE_MEDIATED_ONLY",
              explanation: "A test reaches this only through a fixture.",
              evidence_ids: ["e1"],
            },
          ],
          evidence: [
            {
              evidence_id: "e1",
              side: "target",
              file_path: "src/orders.py",
              symbol: "orders.Order.total",
              start_line: 40,
              end_line: 52,
              content_hash: "h",
              derivation: "static_resolved",
              confidence: 0.9,
            },
          ],
          warnings: ["EVIDENCE_EXCERPT_TRUNCATED"],
          limitations: ["Impact expansion stopped at the depth bound."],
        }),
      },
    });

    const { container } = renderAnalysis("a1");
    await screen.findByTestId("overall-risk");

    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});
