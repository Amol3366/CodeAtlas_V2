import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { apiError, renderWithProviders, stubFetch } from "../../test/harness";
import { Preflight } from "./Preflight";

function report(overrides: Record<string, unknown> = {}) {
  return {
    analysis_id: "an_1",
    status: "complete",
    overall_risk: "medium",
    findings: [
      {
        code: "PUBLIC_BEHAVIOR_CHANGED",
        severity: "medium",
        title: "The behavior of capture changed",
        description: "Statements in the body differ between the two states.",
        derivation: "high_confidence_heuristic",
        confidence: 0.8,
        evidence_ids: ["ev_1"],
      },
      {
        code: "SYMBOL_DELETED",
        severity: "high",
        title: "FakeStore was deleted",
        description: "It no longer exists in the target state.",
        derivation: "deterministic",
        confidence: 1,
        evidence_ids: ["ev_2"],
      },
    ],
    warnings: ["GRAPH_TRUNCATED_DEPTH"],
    limitations: ["Statement classification is syntactic."],
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Preflight", () => {
  it("cannot run without a repository", () => {
    stubFetch({});
    renderWithProviders(<Preflight repositoryId={null} />);
    expect(screen.getByRole("button", { name: "Run preflight" })).toBeDisabled();
  });

  it("orders findings by severity, most severe first", async () => {
    const user = userEvent.setup();
    stubFetch({
      "POST /v1/change-analysis/working-tree": { body: report() },
    });

    renderWithProviders(<Preflight repositoryId="repo_1" />);
    await user.click(screen.getByRole("button", { name: "Run preflight" }));

    const headings = await screen.findAllByRole("heading", { level: 3 });
    const severities = headings
      .map((heading) => heading.textContent)
      .filter((text) => text === "high" || text === "medium");
    expect(severities).toEqual(["high", "medium"]);
  });

  it("shows derivation and confidence for each finding", async () => {
    const user = userEvent.setup();
    stubFetch({
      "POST /v1/change-analysis/working-tree": { body: report() },
    });

    renderWithProviders(<Preflight repositoryId="repo_1" />);
    await user.click(screen.getByRole("button", { name: "Run preflight" }));

    expect(
      await screen.findByText(/high_confidence_heuristic/),
    ).toBeInTheDocument();
    expect(screen.getByText(/deterministic/)).toBeInTheDocument();
  });

  it("shows warnings and limitations rather than hiding them", async () => {
    const user = userEvent.setup();
    stubFetch({
      "POST /v1/change-analysis/working-tree": { body: report() },
    });

    renderWithProviders(<Preflight repositoryId="repo_1" />);
    await user.click(screen.getByRole("button", { name: "Run preflight" }));

    expect(await screen.findByText("GRAPH_TRUNCATED_DEPTH")).toBeInTheDocument();
    expect(
      screen.getByText("Statement classification is syntactic."),
    ).toBeInTheDocument();
  });

  it("does not present an empty report as a safety claim", async () => {
    // "No findings" means no rule matched, which is a different statement from
    // "this change is safe".
    const user = userEvent.setup();
    stubFetch({
      "POST /v1/change-analysis/working-tree": {
        body: report({ findings: [], overall_risk: "none" }),
      },
    });

    renderWithProviders(<Preflight repositoryId="repo_1" />);
    await user.click(screen.getByRole("button", { name: "Run preflight" }));

    expect(
      await screen.findByText(/not a claim that the change is safe/i),
    ).toBeInTheDocument();
  });

  it("reports a failed analysis with its code and stays retryable", async () => {
    const user = userEvent.setup();
    stubFetch({
      "POST /v1/change-analysis/working-tree": {
        status: 409,
        body: apiError(
          "CHANGE_ANALYSIS_REQUIRES_GIT",
          "A working-tree analysis needs a Git base.",
          true,
        ),
      },
    });

    renderWithProviders(<Preflight repositoryId="repo_1" />);
    await user.click(screen.getByRole("button", { name: "Run preflight" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "CHANGE_ANALYSIS_REQUIRES_GIT",
    );
    expect(
      screen.getByRole("button", { name: "Run preflight" }),
    ).toBeEnabled();
  });

  it("shows the overall risk the engine reported", async () => {
    const user = userEvent.setup();
    stubFetch({
      "POST /v1/change-analysis/working-tree": { body: report() },
    });

    renderWithProviders(<Preflight repositoryId="repo_1" />);
    await user.click(screen.getByRole("button", { name: "Run preflight" }));

    expect(await screen.findByTestId("overall-risk")).toHaveTextContent(
      "medium",
    );
  });
});
