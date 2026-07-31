import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import { renderWithProviders, stubFetch } from "../../test/harness";
import { SemanticSettings } from "./SemanticSettings";

/**
 * The only screen where a user can send repository content off their machine.
 *
 * So these tests are about disclosure rather than mechanics: that the
 * consequence is stated in words, that an unavailable option explains itself
 * instead of vanishing, and that the budget a transmitting provider requires is
 * discovered before the save fails rather than after.
 */

const MODELS = {
  models: [
    {
      provider: "none",
      model_id: null,
      dimensions: null,
      available: true,
      transmits_off_machine: false,
      requires: null,
    },
    {
      provider: "local",
      model_id: "sentence-transformers/all-MiniLM-L6-v2",
      dimensions: 384,
      available: true,
      transmits_off_machine: false,
      requires: null,
    },
    {
      provider: "openai",
      model_id: "text-embedding-3-small",
      dimensions: 1536,
      available: false,
      transmits_off_machine: true,
      requires: "extra:semantic-openai and OPENAI_API_KEY",
    },
  ],
};

function stubBackend(overrides: Record<string, unknown> = {}) {
  return stubFetch({
    "/v1/models": { body: MODELS },
    "/v1/settings?repository_id=repo_1": {
      body: {
        repository_id: "repo_1",
        embedding_provider: "none",
        monthly_token_budget: null,
        per_run_token_budget: null,
        transmits_off_machine: false,
        updated_at: "2026-07-30T12:00:00Z",
      },
    },
    "/v1/repositories/repo_1/semantic-status": {
      body: {
        repository_id: "repo_1",
        provider: "none",
        enabled: false,
        snapshot_id: "snap_1",
        coverage: null,
        total_count: null,
        embedded_count: null,
        pending_count: null,
        failed_count: null,
        namespace_id: null,
        model_id: null,
        is_complete: true,
      },
    },
    ...overrides,
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SemanticSettings", () => {
  it("says semantic search is optional", async () => {
    stubBackend();
    renderWithProviders(<SemanticSettings repositoryId="repo_1" />);

    expect(
      await screen.findByText(/semantic search is optional/i),
    ).toBeInTheDocument();
  });

  it("states in words which providers leave the machine", async () => {
    // Section 14.4: never colour alone for a status this consequential.
    stubBackend();
    renderWithProviders(<SemanticSettings repositoryId="repo_1" />);

    expect(
      await screen.findByText(/sends repository content off this machine/i),
    ).toBeInTheDocument();
    expect(
      screen.getAllByText(/stays on this machine/i).length,
    ).toBeGreaterThan(0);
  });

  it("shows an unavailable provider with what it needs", async () => {
    // Hiding it would leave a user unable to discover that installing an extra
    // is all that stands between them and the feature.
    stubBackend();
    renderWithProviders(<SemanticSettings repositoryId="repo_1" />);

    expect(
      await screen.findByText(/requires extra:semantic-openai/i),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/openai/i)).toBeDisabled();
  });

  it("reveals the budget field only for a transmitting provider", async () => {
    stubBackend({
      "/v1/models": {
        body: {
          models: MODELS.models.map((model) =>
            model.provider === "openai"
              ? { ...model, available: true, requires: null }
              : model,
          ),
        },
      },
    });
    renderWithProviders(<SemanticSettings repositoryId="repo_1" />);

    expect(
      screen.queryByLabelText(/monthly token budget/i),
    ).not.toBeInTheDocument();

    await userEvent.click(await screen.findByLabelText(/openai/i));

    expect(
      await screen.findByLabelText(/monthly token budget/i),
    ).toBeInTheDocument();
  });

  it("reports that no provider means nothing to cover", async () => {
    // "Not applicable" is a different fact from 0%, and a coverage bar reading
    // 0% would show every deterministic-only installation as broken.
    stubBackend();
    renderWithProviders(<SemanticSettings repositoryId="repo_1" />);

    expect(
      await screen.findByText(/nothing to cover/i),
    ).toBeInTheDocument();
  });

  it("shows the server's refusal verbatim", async () => {
    // The form is a convenience; the server is the control.
    stubBackend({
      "PATCH /v1/settings?repository_id=repo_1": {
        status: 400,
        body: {
          error: {
            code: "INVALID_REQUEST",
            message:
              "A provider that sends content off the machine requires a monthly token budget.",
            request_id: "req_1",
            retryable: false,
          },
        },
      },
    });
    renderWithProviders(<SemanticSettings repositoryId="repo_1" />);

    await userEvent.click(await screen.findByRole("button", { name: /save/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        /monthly token budget/i,
      );
    });
  });

  it("has no accessibility violations", async () => {
    stubBackend();
    const { container } = renderWithProviders(
      <SemanticSettings repositoryId="repo_1" />,
    );
    await screen.findByText(/semantic search is optional/i);

    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});
