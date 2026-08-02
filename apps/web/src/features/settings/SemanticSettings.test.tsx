import { screen, waitFor, within } from "@testing-library/react";
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
  answer_models: [
    {
      provider: "none",
      model_id: null,
      available: true,
      transmits_off_machine: false,
      requires: null,
    },
    {
      provider: "ollama",
      model_id: "llama3.2:3b",
      available: true,
      transmits_off_machine: false,
      requires: "Ollama running locally",
    },
    {
      provider: "openai",
      model_id: "gpt-4o-mini",
      available: false,
      transmits_off_machine: true,
      requires: "OPENAI_API_KEY",
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
        answer_provider: "none",
        answer_model: null,
        answer_timeout_seconds: null,
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
      (await screen.findAllByText(/sends repository content off this machine/i))
        .length,
    ).toBeGreaterThan(0);
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
    // Scoped to the embedding group. Both fieldsets legitimately offer an
    // OpenAI option, and an unscoped label query matches whichever comes
    // first — which is how a passing test starts asserting the wrong control.
    const embedding = screen
      .getByRole("group", { name: /embedding provider/i });
    expect(within(embedding).getByLabelText(/openai/i)).toBeDisabled();
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

  it("never claims no provider is enabled while coverage is still unknown", async () => {
    // The claim is about privacy, so it may only be made on the server's word.
    // Rendering it as the fallback for every non-success state told a user that
    // nothing was leaving their machine whenever the status request had merely
    // not answered yet — on a repository that may well be transmitting.
    stubBackend({
      "/v1/repositories/repo_1/semantic-status": {
        status: 500,
        body: {
          error: {
            code: "INTERNAL_ERROR",
            message: "boom",
            request_id: "req_test",
            retryable: true,
          },
        },
      },
    });
    renderWithProviders(<SemanticSettings repositoryId="repo_1" />);

    await screen.findByText(/coverage could not be read/i);
    expect(
      screen.queryByText(/no provider is enabled/i),
    ).not.toBeInTheDocument();
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

/**
 * Answer generation is the second provider decision on this page.
 *
 * The tests mirror the embedding ones because the disclosure rules are the
 * same: state the transmit consequence in words, explain an option's
 * requirement rather than hiding it, and reveal the budget a transmitting
 * choice cannot be saved without.
 */
describe("answer provider", () => {
  afterEach(() => vi.restoreAllMocks());

  it("defaults to no answer generation", async () => {
    stubBackend();
    renderWithProviders(<SemanticSettings repositoryId="repo_1" />);

    expect(
      await screen.findByRole("radio", { name: /no answer generation/i }),
    ).toBeChecked();
  });

  it("states in words that the local option stays on this machine", async () => {
    stubBackend();
    renderWithProviders(<SemanticSettings repositoryId="repo_1" />);

    const ollama = await screen.findByRole("radio", { name: /ollama/i });
    expect(ollama.closest("label")).toHaveTextContent(/stays on this machine/i);
  });

  it("says what an option needs rather than hiding it", async () => {
    stubBackend();
    renderWithProviders(<SemanticSettings repositoryId="repo_1" />);

    const ollama = await screen.findByRole("radio", { name: /ollama/i });
    expect(ollama.closest("label")).toHaveTextContent(/requires ollama/i);
  });

  it("hides the model field until generation is switched on", async () => {
    stubBackend();
    renderWithProviders(<SemanticSettings repositoryId="repo_1" />);

    await screen.findByRole("radio", { name: /no answer generation/i });
    expect(screen.queryByLabelText(/answer model/i)).not.toBeInTheDocument();
  });

  it("lets the model be changed so a heavier one can be chosen", async () => {
    stubBackend();
    renderWithProviders(<SemanticSettings repositoryId="repo_1" />);

    await userEvent.click(await screen.findByRole("radio", { name: /ollama/i }));

    const field = screen.getByLabelText(/answer model/i);
    expect(field).toHaveAttribute("placeholder", "llama3.2:3b");

    await userEvent.type(field, "llama3.1:8b");
    expect(field).toHaveValue("llama3.1:8b");
  });

  it("sends the chosen answer provider when saved", async () => {
    const fetchMock = stubBackend();
    renderWithProviders(<SemanticSettings repositoryId="repo_1" />);

    await userEvent.click(await screen.findByRole("radio", { name: /ollama/i }));
    await userEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => {
      const patch = fetchMock.mock.calls.find(
        ([, init]) => (init as RequestInit | undefined)?.method === "PATCH",
      );
      expect(patch).toBeDefined();
      const body = JSON.parse(String((patch?.[1] as RequestInit).body)) as Record<
        string,
        unknown
      >;
      expect(body["answer_provider"]).toBe("ollama");
      // Blank means "use the configured default", stored as null. Sending ""
      // would pin the repository to a nameless model.
      expect(body["answer_model"]).toBeNull();
    });
  });

  it("has no accessibility violations with generation enabled", async () => {
    stubBackend();
    const { container } = renderWithProviders(
      <SemanticSettings repositoryId="repo_1" />,
    );

    await userEvent.click(await screen.findByRole("radio", { name: /ollama/i }));

    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});
