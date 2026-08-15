import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReportNotes } from "./ReportNotes";

describe("ReportNotes", () => {
  it("renders nothing when there is nothing to report", () => {
    const { container } = render(<ReportNotes warnings={[]} limitations={[]} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("explains a known warning code in plain language", () => {
    render(
      <ReportNotes warnings={["EVIDENCE_EXCERPT_TRUNCATED"]} limitations={[]} />,
    );

    expect(screen.getByText(/too long to show in full/i)).toBeInTheDocument();
  });

  it("explains the oversized-file warning in plain language", () => {
    // ADR-0045 made an oversized tracked file a silent skip rather than a
    // refusal, so the warning is the only thing telling a reader the
    // comparison covered less than the tree.
    render(<ReportNotes warnings={["FILE_TOO_LARGE"]} limitations={[]} />);

    expect(screen.getByText(/too large to analyse/i)).toBeInTheDocument();
  });

  it("shows an unknown code as itself rather than dropping it", () => {
    // A code nobody has written prose for is still information. Hiding it
    // would silently shrink what the report disclosed.
    render(<ReportNotes warnings={["SOME_NEW_CODE"]} limitations={[]} />);

    expect(screen.getByText("SOME_NEW_CODE")).toBeInTheDocument();
  });

  it("renders limitations verbatim", () => {
    // Limitations are already prose from the backend, not codes.
    render(
      <ReportNotes
        warnings={[]}
        limitations={["Impact expansion stopped at the depth bound."]}
      />,
    );

    expect(screen.getByText(/stopped at the depth bound/i)).toBeInTheDocument();
  });
});
