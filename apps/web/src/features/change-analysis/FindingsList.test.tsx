import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

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

describe("FindingsList: two findings sharing a code and title", () => {
  const pair = [
    finding({ subject: "total", file_path: "orders.py", evidence_ids: ["e1"] }),
    finding({ subject: "total", file_path: "billing.py", evidence_ids: ["e2"] }),
  ];

  it("gives each one a distinct React key", () => {
    // Asserting both are *rendered* does not test this: React renders both
    // whatever the key, and reverting the key to `code-title` left such a test
    // green. The duplicate key surfaces only as a console warning, so that is
    // what this pins.
    const warnings: unknown[][] = [];
    const spy = vi
      .spyOn(console, "error")
      .mockImplementation((...args: unknown[]) => {
        warnings.push(args);
      });
    try {
      render(<FindingsList findings={pair} evidence={noEvidence} />);
    } finally {
      spy.mockRestore();
    }

    const duplicate = warnings.filter((args) =>
      String(args[0] ?? "").includes("same key"),
    );
    expect(duplicate).toHaveLength(0);
    expect(screen.getAllByText("Public contract changed")).toHaveLength(2);
  });

  it("shows which file each one is about", () => {
    render(<FindingsList findings={pair} evidence={noEvidence} />);

    expect(screen.getByText("orders.py")).toBeInTheDocument();
    expect(screen.getByText("billing.py")).toBeInTheDocument();
    expect(screen.getAllByText("total")).toHaveLength(2);
  });

  it("does not invent a subject for a finding that has none", () => {
    // The analysis returns null when it could not locate the finding, and a
    // confident-looking subject there would be exactly the invention the
    // evidence contract forbids.
    render(
      <FindingsList
        findings={[finding({ evidence_ids: ["e1"] })]}
        evidence={noEvidence}
      />,
    );

    expect(screen.queryByText(/ in /)).not.toBeInTheDocument();
  });
});
