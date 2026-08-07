import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TestGaps } from "./TestGaps";
import type { ChangeEvidenceItem, GapReason } from "./useAnalysis";

const noEvidence = new Map<string, ChangeEvidenceItem>();

function reason(overrides: Partial<GapReason> = {}): GapReason {
  return {
    qualified_name: "orders.Order",
    reason: "FIXTURE_MEDIATED_ONLY",
    explanation: "A test reaches this only through a fixture.",
    evidence_ids: [],
    ...overrides,
  } as GapReason;
}

describe("TestGaps", () => {
  it("renders nothing when there are no gaps", () => {
    const { container } = render(
      <TestGaps gaps={[]} reasons={[]} evidence={noEvidence} />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("always shows the disclaimer when any gap is shown", () => {
    // CodeAtlas does not execute tests and cannot claim a symbol is uncovered.
    render(
      <TestGaps
        gaps={["orders.Order"]}
        reasons={[reason()]}
        evidence={noEvidence}
      />,
    );

    expect(
      screen.getByText(/does not prove absence of coverage/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/does not execute tests/i)).toBeInTheDocument();
  });

  it("calls the section possible test gaps, never untested", () => {
    render(
      <TestGaps
        gaps={["orders.Order"]}
        reasons={[reason()]}
        evidence={noEvidence}
      />,
    );

    expect(
      screen.getByRole("heading", { name: /possible test gaps/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/untested/i)).not.toBeInTheDocument();
  });

  it("shows each gap with its reason and explanation", () => {
    render(
      <TestGaps
        gaps={["orders.Order"]}
        reasons={[reason()]}
        evidence={noEvidence}
      />,
    );

    expect(screen.getByText("orders.Order")).toBeInTheDocument();
    expect(screen.getByText("FIXTURE_MEDIATED_ONLY")).toBeInTheDocument();
    expect(screen.getByText(/only through a fixture/i)).toBeInTheDocument();
  });

  it("shows a gap that has no matching reason", () => {
    // The name is real even if no reason accompanied it; dropping it would
    // under-report the gap list.
    render(<TestGaps gaps={["orders.Order"]} reasons={[]} evidence={noEvidence} />);

    expect(screen.getByText("orders.Order")).toBeInTheDocument();
  });

  it("renders no evidence reference for NO_TEST_FILE_REFERENCE", () => {
    // An absence is reported as an absence, never dressed in a citation.
    render(
      <TestGaps
        gaps={["orders.Order"]}
        reasons={[reason({ reason: "NO_TEST_FILE_REFERENCE", evidence_ids: [] })]}
        evidence={noEvidence}
      />,
    );

    expect(screen.queryByText(/lines/)).not.toBeInTheDocument();
  });
});
