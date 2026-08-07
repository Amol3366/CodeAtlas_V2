import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FindingsList } from "./FindingsList";
import type { ChangeEvidenceItem, Finding } from "./useAnalysis";

function finding(overrides: Partial<Finding> = {}): Finding {
  return {
    code: "PUBLIC_CONTRACT_CHANGED",
    severity: "high",
    title: "Public contract changed",
    description: "The signature changed.",
    derivation: "static_resolved",
    confidence: 0.9,
    evidence_ids: [],
    ...overrides,
  } as Finding;
}

const noEvidence = new Map<string, ChangeEvidenceItem>();

describe("FindingsList", () => {
  it("says an empty result is not a safety claim", () => {
    render(<FindingsList findings={[]} evidence={noEvidence} />);

    expect(
      screen.getByText(/not a claim that the change is safe/i),
    ).toBeInTheDocument();
  });

  it("groups findings by severity, most severe first", () => {
    render(
      <FindingsList
        findings={[
          finding({ severity: "low", title: "Low one" }),
          finding({ severity: "critical", title: "Critical one" }),
        ]}
        evidence={noEvidence}
      />,
    );

    const headings = screen.getAllByRole("heading", { level: 3 });
    expect(headings[0]).toHaveTextContent(/critical/i);
  });

  it("shows derivation and confidence as separate facts", () => {
    render(<FindingsList findings={[finding()]} evidence={noEvidence} />);

    expect(screen.getByText(/static_resolved/)).toBeInTheDocument();
    expect(screen.getByText(/0\.90/)).toBeInTheDocument();
  });

  it("renders an evidence reference for each cited id", () => {
    const evidence = new Map<string, ChangeEvidenceItem>([
      [
        "e1",
        {
          evidence_id: "e1",
          side: "target",
          file_path: "src/orders.py",
          symbol: null,
          start_line: 1,
          end_line: 2,
          content_hash: "h",
          derivation: "deterministic",
          confidence: 1,
        } as ChangeEvidenceItem,
      ],
    ]);

    render(
      <FindingsList
        findings={[finding({ evidence_ids: ["e1"] })]}
        evidence={evidence}
      />,
    );

    expect(screen.getByText("src/orders.py")).toBeInTheDocument();
  });

  it("silently skips a citation whose evidence is absent", () => {
    // Rendering a placeholder for missing evidence would invent a citation.
    render(
      <FindingsList
        findings={[finding({ evidence_ids: ["missing"] })]}
        evidence={noEvidence}
      />,
    );

    expect(screen.getByText("Public contract changed")).toBeInTheDocument();
  });
});
