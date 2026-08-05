import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { MessageEvidence } from "../../lib/conversations";
import { apiError, renderWithProviders, stubFetch } from "../../test/harness";
import { EvidenceDrawer } from "./EvidenceDrawer";

const REPOSITORY_ID = "repo_1";

/**
 * The URL the drawer actually requests, query string included.
 *
 * Spelled out rather than pattern-matched on purpose. An earlier version of
 * this suite stubbed a bare `/v1/evidence/ev_1` returning a flat object, and
 * both were fictions: the endpoint requires `repository_id` and answers with
 * the standard query envelope. These tests passed while the drawer had never
 * once rendered a real excerpt. A stub that must name the whole contract is a
 * stub that fails when the contract moves.
 */
const EVIDENCE_URL = `/v1/evidence/ev_1?repository_id=${REPOSITORY_ID}`;

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

/** The `QueryResponse` envelope, trimmed to what the drawer reads from it. */
function envelope(
  overrides: Partial<{
    evidence_id: string;
    excerpt: string;
    validation: string;
  }> = {},
) {
  return {
    contract_version: "1.0",
    request_id: "req_test",
    repository_id: REPOSITORY_ID,
    evidence: [
      {
        evidence_id: "ev_1",
        repository_id: REPOSITORY_ID,
        snapshot_id: "snap_old",
        file_path: "src/payments/service.py",
        symbol: "PaymentService.capture",
        start_line: 7,
        end_line: 8,
        excerpt: "def capture(self, key):\n    return self.store.claim(key)",
        content_hash: "abc",
        derivation: "high_confidence_heuristic",
        confidence: 0.8,
        validation: "valid",
        ...overrides,
      },
    ],
  };
}

function renderDrawer(onClose: () => void = vi.fn()) {
  return renderWithProviders(
    <EvidenceDrawer
      evidence={citation}
      repositoryId={REPOSITORY_ID}
      onClose={onClose}
    />,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("EvidenceDrawer", () => {
  it("renders nothing when no citation is open", () => {
    stubFetch({});
    renderWithProviders(
      <EvidenceDrawer
        evidence={null}
        repositoryId={REPOSITORY_ID}
        onClose={vi.fn()}
      />,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows the path, symbol, and line range", async () => {
    stubFetch({ [EVIDENCE_URL]: { body: envelope() } });
    renderDrawer();

    expect(
      await screen.findByText("src/payments/service.py:7-8"),
    ).toBeInTheDocument();
    expect(screen.getByText("PaymentService.capture")).toBeInTheDocument();
  });

  it("requests the evidence within its repository", async () => {
    // An evidence ID is not addressable on its own: it is only meaningful
    // inside the snapshot of one repository.
    const handler = stubFetch({ [EVIDENCE_URL]: { body: envelope() } });
    renderDrawer();

    await screen.findByTestId("excerpt");
    expect(handler).toHaveBeenCalledWith(EVIDENCE_URL, expect.anything());
  });

  it("states derivation and confidence as separate facts", async () => {
    // A high-confidence heuristic is still a heuristic; collapsing the two
    // would let a reader take it for a deterministic result.
    stubFetch({ [EVIDENCE_URL]: { body: envelope() } });
    renderDrawer();

    expect(await screen.findByTestId("derivation")).toHaveTextContent(
      "high_confidence_heuristic",
    );
    expect(screen.getByText("0.80")).toBeInTheDocument();
  });

  it("shows the snapshot the answer used, not the current one", async () => {
    stubFetch({ [EVIDENCE_URL]: { body: envelope() } });
    renderDrawer();

    expect(await screen.findByTestId("evidence-snapshot")).toHaveTextContent(
      "snap_old",
    );
  });

  it("renders the excerpt as text, never as markup", async () => {
    stubFetch({
      [EVIDENCE_URL]: {
        body: envelope({ excerpt: "<script>window.pwned = true</script>" }),
      },
    });

    const { container } = renderDrawer();

    const excerpt = await screen.findByTestId("excerpt");
    expect(excerpt).toHaveTextContent("<script>window.pwned = true</script>");
    expect(container.querySelector("script")).toBeNull();
    expect((window as unknown as Record<string, unknown>).pwned).toBeUndefined();
  });

  it("refuses to show an excerpt that failed verification", async () => {
    // Showing current file contents under an old citation is the substitution
    // the evidence contract exists to prevent.
    stubFetch({
      [EVIDENCE_URL]: { body: envelope({ validation: "invalid" }) },
    });
    renderDrawer();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /could not be verified/i,
    );
    expect(screen.queryByTestId("excerpt")).not.toBeInTheDocument();
  });

  it("refuses to show an excerpt the response never contained", async () => {
    // A 200 that omits the cited evidence is not a success. Falling back to the
    // envelope's first item would show source under someone else's citation.
    stubFetch({
      [EVIDENCE_URL]: { body: envelope({ evidence_id: "ev_other" }) },
    });
    renderDrawer();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /could not be verified/i,
    );
    expect(screen.queryByTestId("excerpt")).not.toBeInTheDocument();
  });

  it("reports a missing evidence row with its code", async () => {
    stubFetch({
      [EVIDENCE_URL]: {
        status: 404,
        body: apiError("EVIDENCE_NOT_FOUND", "No evidence matches that ID."),
      },
    });
    renderDrawer();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "EVIDENCE_NOT_FOUND",
    );
  });

  it("is a labelled dialog", async () => {
    stubFetch({ [EVIDENCE_URL]: { body: envelope() } });
    renderDrawer();

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleName(/Evidence/);
  });

  it("moves focus to the drawer when it opens", async () => {
    stubFetch({ [EVIDENCE_URL]: { body: envelope() } });
    renderDrawer();

    expect(
      await screen.findByRole("button", { name: "Close evidence" }),
    ).toHaveFocus();
  });

  it("returns focus to the opener when it unmounts", async () => {
    // The panel is unmounted on close rather than left mounted with no
    // evidence, so the focus contract has to survive unmount — not just a
    // prop change. A keyboard user who closes the panel must land back on the
    // citation they opened, never on the document body.
    stubFetch({ [EVIDENCE_URL]: { body: envelope() } });

    function Harness({ open }: { readonly open: boolean }) {
      return (
        <>
          <button type="button">Evidence 1</button>
          {open ? (
            <EvidenceDrawer
              evidence={citation}
              repositoryId={REPOSITORY_ID}
              onClose={vi.fn()}
            />
          ) : null}
        </>
      );
    }

    const { rerender } = renderWithProviders(<Harness open={false} />);
    const opener = screen.getByRole("button", { name: "Evidence 1" });
    opener.focus();
    expect(opener).toHaveFocus();

    rerender(<Harness open />);
    expect(
      await screen.findByRole("button", { name: "Close evidence" }),
    ).toHaveFocus();

    rerender(<Harness open={false} />);

    expect(opener).toHaveFocus();
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    stubFetch({ [EVIDENCE_URL]: { body: envelope() } });

    renderDrawer(onClose);
    await screen.findByRole("dialog");
    await user.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalled();
  });

  it("closes from the close button", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    stubFetch({ [EVIDENCE_URL]: { body: envelope() } });

    renderDrawer(onClose);
    await user.click(
      await screen.findByRole("button", { name: "Close evidence" }),
    );

    expect(onClose).toHaveBeenCalled();
  });
});
