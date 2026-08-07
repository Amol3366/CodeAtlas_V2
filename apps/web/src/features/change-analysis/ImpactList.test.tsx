import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ImpactList } from "./ImpactList";
import type { ImpactEdge } from "./useAnalysis";

function edge(overrides: Partial<ImpactEdge> = {}): ImpactEdge {
  return {
    source: "orders.Order.total",
    kind: "CALLS",
    target: "api.checkout",
    derivation: "static_resolved",
    confidence: 0.9,
    ...overrides,
  } as ImpactEdge;
}

describe("ImpactList", () => {
  it("shows source, relation and target", () => {
    render(<ImpactList edges={[edge()]} />);

    expect(screen.getByText("orders.Order.total")).toBeInTheDocument();
    expect(screen.getByText(/CALLS/)).toBeInTheDocument();
    expect(screen.getByText("api.checkout")).toBeInTheDocument();
  });

  it("shows the derivation on EVERY edge", () => {
    // ADR-0016: a fixture-mediated TESTS edge is a candidate, not coverage.
    // Rendering an edge without its derivation would undo that distinction.
    render(
      <ImpactList
        edges={[
          edge(),
          edge({
            kind: "TESTS",
            target: "test_total",
            derivation: "low_confidence_heuristic",
          }),
        ]}
      />,
    );

    expect(screen.getByText("static_resolved")).toBeInTheDocument();
    expect(screen.getByText("low_confidence_heuristic")).toBeInTheDocument();
  });

  it("renders nothing when there are no edges", () => {
    const { container } = render(<ImpactList edges={[]} />);

    expect(container).toBeEmptyDOMElement();
  });
});
