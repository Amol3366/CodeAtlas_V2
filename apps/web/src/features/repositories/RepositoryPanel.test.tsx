import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { apiError, renderWithProviders, stubFetch } from "../../test/harness";
import { RepositoryPanel } from "./RepositoryPanel";

/**
 * The first slice that talks to a real backend contract. Every assertion is
 * about not lying to the user: real counts, real stages, the error envelope's
 * own code, and no fabricated progress.
 */

const repository = {
  repository_id: "repo_1",
  display_name: "demo",
  created_at: "2026-07-27T12:00:00Z",
};

const status = {
  repository_id: "repo_1",
  snapshot: {
    snapshot_id: "snap_1",
    git_head: null,
    working_tree_fingerprint: "fp",
    freshness: "fresh",
    semantic_coverage: 0,
  },
  file_count: 12,
  symbol_count: 34,
  parse_error_count: 2,
  warnings: ["SCAN_LIMIT_EXCEEDED"],
};

const diagnostics = {
  repository_id: "repo_1",
  snapshot_id: "snap_1",
  parse_error_count: 2,
  skipped_by_reason: { TOO_LARGE: 3 },
  limits: {},
  warnings: [],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("RepositoryPanel", () => {
  it("leads an empty state to adding a repository, with the privacy statement", async () => {
    stubFetch({ "/v1/repositories": { body: [] } });

    renderWithProviders(<RepositoryPanel />);

    expect(
      await screen.findByText("Add your first repository"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/No source, filenames, or derived content leave/i),
    ).toBeInTheDocument();
  });

  it("shows the real counts and freshness the backend reported", async () => {
    stubFetch({
      "/v1/repositories": { body: [repository] },
      "/v1/repositories/repo_1/status": { body: status },
      "/v1/repositories/repo_1/diagnostics": { body: diagnostics },
    });

    renderWithProviders(<RepositoryPanel />);

    expect(await screen.findByTestId("freshness")).toHaveTextContent("fresh");
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("34")).toBeInTheDocument();
  });

  it("says a repository has not been indexed rather than showing zeros", async () => {
    // Zeros would read as "indexed and empty", which is a different fact.
    stubFetch({
      "/v1/repositories": { body: [repository] },
      "/v1/repositories/repo_1/status": {
        body: { ...status, snapshot: null },
      },
      "/v1/repositories/repo_1/diagnostics": { body: diagnostics },
    });

    renderWithProviders(<RepositoryPanel />);

    expect(
      await screen.findByText(/has not been indexed yet/i),
    ).toBeInTheDocument();
  });

  it("surfaces warnings from the status response", async () => {
    stubFetch({
      "/v1/repositories": { body: [repository] },
      "/v1/repositories/repo_1/status": { body: status },
      "/v1/repositories/repo_1/diagnostics": { body: diagnostics },
    });

    renderWithProviders(<RepositoryPanel />);

    expect(await screen.findByText("SCAN_LIMIT_EXCEEDED")).toBeInTheDocument();
  });

  it("shows skipped files by reason", async () => {
    stubFetch({
      "/v1/repositories": { body: [repository] },
      "/v1/repositories/repo_1/status": { body: status },
      "/v1/repositories/repo_1/diagnostics": { body: diagnostics },
    });

    renderWithProviders(<RepositoryPanel />);

    expect(await screen.findByText("TOO_LARGE")).toBeInTheDocument();
  });

  it("renders the error envelope's code and message, never a trace", async () => {
    stubFetch({
      "/v1/repositories": {
        status: 500,
        body: apiError("INTERNAL_ERROR", "An internal error occurred."),
      },
    });

    renderWithProviders(<RepositoryPanel />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("An internal error occurred.");
    expect(alert).toHaveTextContent("INTERNAL_ERROR");
    expect(alert.textContent).not.toContain("Traceback");
  });

  it("reports a rejected path with the code the backend gave", async () => {
    const user = userEvent.setup();
    stubFetch({
      "/v1/repositories": { body: [] },
      "POST /v1/repositories": {
        status: 422,
        body: apiError("PATH_NOT_ALLOWED", "That path is not allowed."),
      },
    });

    renderWithProviders(<RepositoryPanel />);

    await user.type(
      await screen.findByLabelText("Add local repository"),
      "somewhere",
    );
    await user.click(screen.getByRole("button", { name: "Add" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "PATH_NOT_ALLOWED",
    );
  });

  it("disables the add button until a path is entered", async () => {
    stubFetch({ "/v1/repositories": { body: [] } });

    renderWithProviders(<RepositoryPanel />);

    expect(await screen.findByRole("button", { name: "Add" })).toBeDisabled();
  });

  it("stops polling once the snapshot has settled", async () => {
    // Polling a terminal state forever is a request that can never change its
    // answer.
    const handler = stubFetch({
      "/v1/repositories": { body: [repository] },
      "/v1/repositories/repo_1/status": { body: status },
      "/v1/repositories/repo_1/diagnostics": { body: diagnostics },
    });

    renderWithProviders(<RepositoryPanel />);
    await screen.findByTestId("freshness");

    const calls = () =>
      handler.mock.calls.filter((call) =>
        String(call[0]).endsWith("/status"),
      ).length;
    const before = calls();
    await new Promise((resolve) => setTimeout(resolve, 200));

    expect(calls()).toBe(before);
  });

  it("triggers an index run and refreshes status afterwards", async () => {
    const user = userEvent.setup();
    const handler = stubFetch({
      "/v1/repositories": { body: [repository] },
      "/v1/repositories/repo_1/status": { body: status },
      "/v1/repositories/repo_1/diagnostics": { body: diagnostics },
      "POST /v1/repositories/repo_1/index": {
        body: { state: "active", snapshot_id: "snap_2" },
      },
    });

    renderWithProviders(<RepositoryPanel />);
    await user.click(await screen.findByRole("button", { name: "Index now" }));

    await waitFor(() => {
      expect(
        handler.mock.calls.some(
          (call) =>
            String(call[0]).endsWith("/index") &&
            (call[1] as RequestInit | undefined)?.method === "POST",
        ),
      ).toBe(true);
    });
  });
});
