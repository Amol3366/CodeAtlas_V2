import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { MessageEvidence } from "../../lib/conversations";
import { apiError, renderWithProviders, stubFetch } from "../../test/harness";
import { EvidenceDrawer } from "./EvidenceDrawer";

const citation: MessageEvidence = {
  evidence_id: "ev_1",
  citation_ordinal: 1,
  file_path: "src/payments/service.py",
  symbol: "PaymentService.capture",
  start_line: 7,
  end_line: 8,
  content_hash: "abc",
  derivation: "high_confidence_heuristic",
  confidence: 0.8,
  snapshot_id: "snap_old",
};

const fetched = {
  evidence_id: "ev_1",
  file_path: "src/payments/service.py",
  symbol: "PaymentService.capture",
  start_line: 7,
  end_line: 8,
  excerpt: "def capture(self, key):\n    return self.store.claim(key)",
  derivation: "high_confidence_heuristic",
  confidence: 0.8,
  validation: "valid",
  snapshot_id: "snap_old",
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("EvidenceDrawer", () => {
  it("renders nothing when no citation is open", () => {
    stubFetch({});
    renderWithProviders(
      <EvidenceDrawer evidence={null} onClose={vi.fn()} />,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows the path, symbol, and line range", async () => {
    stubFetch({ "/v1/evidence/ev_1": { body: fetched } });

    renderWithProviders(
      <EvidenceDrawer evidence={citation} onClose={vi.fn()} />,
    );

    expect(
      await screen.findByText("src/payments/service.py:7-8"),
    ).toBeInTheDocument();
    expect(screen.getByText("PaymentService.capture")).toBeInTheDocument();
  });

  it("states derivation and confidence as separate facts", async () => {
    // A high-confidence heuristic is still a heuristic; collapsing the two
    // would let a reader take it for a deterministic result.
    stubFetch({ "/v1/evidence/ev_1": { body: fetched } });

    renderWithProviders(
      <EvidenceDrawer evidence={citation} onClose={vi.fn()} />,
    );

    expect(await screen.findByTestId("derivation")).toHaveTextContent(
      "high_confidence_heuristic",
    );
    expect(screen.getByText("0.80")).toBeInTheDocument();
  });

  it("shows the snapshot the answer used, not the current one", async () => {
    stubFetch({ "/v1/evidence/ev_1": { body: fetched } });

    renderWithProviders(
      <EvidenceDrawer evidence={citation} onClose={vi.fn()} />,
    );

    expect(await screen.findByTestId("evidence-snapshot")).toHaveTextContent(
      "snap_old",
    );
  });

  it("renders the excerpt as text, never as markup", async () => {
    stubFetch({
      "/v1/evidence/ev_1": {
        body: { ...fetched, excerpt: "<script>window.pwned = true</script>" },
      },
    });

    const { container } = renderWithProviders(
      <EvidenceDrawer evidence={citation} onClose={vi.fn()} />,
    );

    const excerpt = await screen.findByTestId("excerpt");
    expect(excerpt).toHaveTextContent("<script>window.pwned = true</script>");
    expect(container.querySelector("script")).toBeNull();
    expect((window as unknown as Record<string, unknown>).pwned).toBeUndefined();
  });

  it("refuses to show an excerpt that failed verification", async () => {
    // Showing current file contents under an old citation is the substitution
    // the evidence contract exists to prevent.
    stubFetch({
      "/v1/evidence/ev_1": {
        body: { ...fetched, validation: "stale_file_content" },
      },
    });

    renderWithProviders(
      <EvidenceDrawer evidence={citation} onClose={vi.fn()} />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /could not be verified/i,
    );
    expect(screen.queryByTestId("excerpt")).not.toBeInTheDocument();
  });

  it("reports a missing evidence row with its code", async () => {
    stubFetch({
      "/v1/evidence/ev_1": {
        status: 404,
        body: apiError("EVIDENCE_NOT_FOUND", "No evidence matches that ID."),
      },
    });

    renderWithProviders(
      <EvidenceDrawer evidence={citation} onClose={vi.fn()} />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "EVIDENCE_NOT_FOUND",
    );
  });

  it("is a labelled dialog", async () => {
    stubFetch({ "/v1/evidence/ev_1": { body: fetched } });

    renderWithProviders(
      <EvidenceDrawer evidence={citation} onClose={vi.fn()} />,
    );

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleName(/Evidence/);
  });

  it("moves focus to the drawer when it opens", async () => {
    stubFetch({ "/v1/evidence/ev_1": { body: fetched } });

    renderWithProviders(
      <EvidenceDrawer evidence={citation} onClose={vi.fn()} />,
    );

    expect(
      await screen.findByRole("button", { name: "Close evidence" }),
    ).toHaveFocus();
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    stubFetch({ "/v1/evidence/ev_1": { body: fetched } });

    renderWithProviders(
      <EvidenceDrawer evidence={citation} onClose={onClose} />,
    );
    await screen.findByRole("dialog");
    await user.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalled();
  });

  it("closes from the close button", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    stubFetch({ "/v1/evidence/ev_1": { body: fetched } });

    renderWithProviders(
      <EvidenceDrawer evidence={citation} onClose={onClose} />,
    );
    await user.click(
      await screen.findByRole("button", { name: "Close evidence" }),
    );

    expect(onClose).toHaveBeenCalled();
  });
});
