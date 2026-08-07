import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EvidenceRef } from "./EvidenceRef";
import type { ChangeEvidenceItem } from "./useAnalysis";

function item(overrides: Partial<ChangeEvidenceItem> = {}): ChangeEvidenceItem {
  return {
    evidence_id: "e1",
    side: "target",
    file_path: "src/orders.py",
    symbol: "orders.Order.total",
    start_line: 40,
    end_line: 52,
    content_hash: "h",
    derivation: "static_resolved",
    confidence: 0.9,
    ...overrides,
  } as ChangeEvidenceItem;
}

describe("EvidenceRef", () => {
  it("shows where the evidence is", () => {
    render(<EvidenceRef item={item()} />);

    expect(screen.getByText("src/orders.py")).toBeInTheDocument();
    expect(screen.getByText(/40.*52/)).toBeInTheDocument();
  });

  it("shows derivation and confidence as separate facts", () => {
    // A high confidence score never implies a stronger derivation.
    render(<EvidenceRef item={item()} />);

    expect(screen.getByText("static_resolved")).toBeInTheDocument();
    expect(screen.getByText(/0\.90/)).toBeInTheDocument();
  });

  it("labels base-side evidence as historical", () => {
    // Base side is read from a commit and can never be re-verified against the
    // working tree. It is historical, which is not the same as stale.
    render(<EvidenceRef item={item({ side: "base" })} />);

    expect(screen.getByText(/historical/i)).toBeInTheDocument();
  });

  it("does not label target-side evidence as historical", () => {
    render(<EvidenceRef item={item({ side: "target" })} />);

    expect(screen.queryByText(/historical/i)).not.toBeInTheDocument();
  });
});
