import { QueryClient } from "@tanstack/react-query";
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
        embedding_model: null,
      },
    },
    // The component asks for this on every render, so it belongs in the
    // defaults rather than in each test's overrides: without it every existing
    // test in this file fails with a NOT_STUBBED 500 that has nothing to do
    // with what it was asserting.
    "/v1/credentials": {
      body: {
        openai: { configured: false, source: null, store_available: true },
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
  it("waits for fresh settings data instead of rendering cached route data", async () => {
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false, gcTime: 0 },
        mutations: { retry: false },
      },
    });
    client.setQueryData(["settings", "repo_1"], {
      repository_id: "repo_1",
      embedding_provider: "none",
      monthly_token_budget: null,
      per_run_token_budget: null,
      transmits_off_machine: false,
      updated_at: "2026-07-30T12:00:00Z",
      answer_provider: "none",
      answer_model: null,
      answer_timeout_seconds: null,
      embedding_model: null,
    });
    client.setQueryData(["models"], {
      models: MODELS.models,
      answer_models: [],
    });
    stubBackend();

    renderWithProviders(<SemanticSettings repositoryId="repo_1" />, {
      client,
    });

    expect(
      screen.getByRole("status", { name: /loading provider settings/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/no answer providers are available/i),
    ).not.toBeInTheDocument();
    expect(
      await screen.findByRole("radio", { name: /ollama/i }),
    ).toBeInTheDocument();
  });

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

    // Scoped, and anchored. The page now also carries an "OpenAI API key"
    // field, so an unscoped /openai/i matches two different controls.
    await userEvent.click(
      await within(
        await screen.findByRole("group", { name: /embedding provider/i }),
      ).findByLabelText(/openai/i),
    );

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

  it("explains custom embedding dimensions are auto-detected", async () => {
    stubBackend({
      "/v1/models": {
        body: {
          ...MODELS,
          models: MODELS.models.map((model) =>
            model.provider === "local"
              ? {
                  ...model,
                  model_id: "BAAI/bge-small-en-v1.5",
                  dimensions: null,
                }
              : model,
          ),
        },
      },
    });
    renderWithProviders(<SemanticSettings repositoryId="repo_1" />);

    expect(
      await screen.findByText(/dimensions auto-detected/i),
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

    await userEvent.click(
      await screen.findByRole("button", { name: /^save$/i }),
    );

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
    await userEvent.click(screen.getByRole("button", { name: /^save$/i }));

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


  describe("choosing an embedding model", () => {
    it("shows the model field only for the local provider", async () => {
      stubBackend();
      renderWithProviders(<SemanticSettings repositoryId="repo_1" />);

      await userEvent.click(
        await screen.findByRole("radio", { name: /local model/i }),
      );

      expect(screen.getByLabelText(/embedding model/i)).toBeInTheDocument();
    });

    it("hides the model field while no local provider is selected", async () => {
      stubBackend();
      renderWithProviders(<SemanticSettings repositoryId="repo_1" />);

      await screen.findByRole("radio", { name: /local model/i });

      expect(screen.queryByLabelText(/embedding model/i)).not.toBeInTheDocument();
    });

    it("blocks saving a typed model until it has been checked", async () => {
      stubBackend();
      renderWithProviders(<SemanticSettings repositoryId="repo_1" />);

      await userEvent.click(
        await screen.findByRole("radio", { name: /local model/i }),
      );
      await userEvent.type(
        screen.getByLabelText(/embedding model/i),
        "BAAI/bge-small-en-v1.5",
      );

      expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
    });

    it("reports the measured dimensions after a successful check", async () => {
      stubBackend({
        "/v1/models/embedding/validate": {
          body: {
            provider: "local",
            model_id: "BAAI/bge-small-en-v1.5",
            ok: true,
            dimensions: 384,
            detail_code: null,
            latency_ms: 120,
          },
        },
      });
      renderWithProviders(<SemanticSettings repositoryId="repo_1" />);

      await userEvent.click(
        await screen.findByRole("radio", { name: /local model/i }),
      );
      await userEvent.type(
        screen.getByLabelText(/embedding model/i),
        "BAAI/bge-small-en-v1.5",
      );
      await userEvent.click(
        screen.getByRole("button", { name: /check model/i }),
      );

      // Scoped to the check result: the provider card also states the
      // default model's width, so a bare /384 dimensions/ matches twice.
      expect(
        await screen.findByText(/loaded, 384 dimensions/i),
      ).toBeInTheDocument();
      await waitFor(() => {
        expect(screen.getByRole("button", { name: /^save$/i })).toBeEnabled();
      });
    });

    it("offers re-embedding when the saved model differs from the active one", async () => {
      stubBackend({
        "/v1/settings?repository_id=repo_1": {
          body: {
            repository_id: "repo_1",
            embedding_provider: "local",
            monthly_token_budget: null,
            per_run_token_budget: null,
            transmits_off_machine: false,
            updated_at: "2026-07-30T12:00:00Z",
            answer_provider: "none",
            answer_model: null,
            answer_timeout_seconds: null,
            embedding_model: "BAAI/bge-small-en-v1.5",
          },
        },
        "/v1/repositories/repo_1/semantic-status": {
          body: {
            repository_id: "repo_1",
            provider: "local",
            enabled: true,
            snapshot_id: "snap_1",
            coverage: 1,
            total_count: 10,
            embedded_count: 10,
            pending_count: 0,
            failed_count: 0,
            namespace_id: "ns_1",
            model_id: "sentence-transformers/all-MiniLM-L6-v2",
            is_complete: true,
          },
        },
      });
      renderWithProviders(<SemanticSettings repositoryId="repo_1" />);

      expect(
        await screen.findByRole("button", { name: /re-embed/i }),
      ).toBeInTheDocument();
    });

    it("does not offer re-embedding when the active model already matches", async () => {
      stubBackend({
        "/v1/settings?repository_id=repo_1": {
          body: {
            repository_id: "repo_1",
            embedding_provider: "local",
            monthly_token_budget: null,
            per_run_token_budget: null,
            transmits_off_machine: false,
            updated_at: "2026-07-30T12:00:00Z",
            answer_provider: "none",
            answer_model: null,
            answer_timeout_seconds: null,
            embedding_model: "sentence-transformers/all-MiniLM-L6-v2",
          },
        },
        "/v1/repositories/repo_1/semantic-status": {
          body: {
            repository_id: "repo_1",
            provider: "local",
            enabled: true,
            snapshot_id: "snap_1",
            coverage: 1,
            total_count: 10,
            embedded_count: 10,
            pending_count: 0,
            failed_count: 0,
            namespace_id: "ns_1",
            model_id: "sentence-transformers/all-MiniLM-L6-v2",
            is_complete: true,
          },
        },
      });
      renderWithProviders(<SemanticSettings repositoryId="repo_1" />);

      await screen.findByLabelText(/embedding model/i);

      expect(
        screen.queryByRole("button", { name: /re-embed/i }),
      ).not.toBeInTheDocument();
    });

    it("keeps saving blocked when the check fails", async () => {
      stubBackend({
        "/v1/models/embedding/validate": {
          body: {
            provider: "local",
            model_id: "nope/not-a-model",
            ok: false,
            dimensions: null,
            detail_code: "PROVIDER_UNAVAILABLE",
            latency_ms: 30,
          },
        },
      });
      renderWithProviders(<SemanticSettings repositoryId="repo_1" />);

      await userEvent.click(
        await screen.findByRole("radio", { name: /local model/i }),
      );
      await userEvent.type(
        screen.getByLabelText(/embedding model/i),
        "nope/not-a-model",
      );
      await userEvent.click(
        screen.getByRole("button", { name: /check model/i }),
      );

      expect(
        await screen.findByText(/could not load nope\/not-a-model/i),
      ).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
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

describe("the OpenAI API key", () => {
  it("never populates the key field from the server", async () => {
    stubBackend({
      "/v1/credentials": {
        body: {
          openai: {
            configured: true,
            source: "credential_store",
            store_available: true,
          },
        },
      },
    });
    renderWithProviders(<SemanticSettings repositoryId="repo_1" />);

    const field = await screen.findByLabelText(/openai api key/i);
    expect(field).toHaveAttribute("type", "password");
    expect(field).toHaveValue("");
  });

  it("says where a configured key came from", async () => {
    stubBackend({
      "/v1/credentials": {
        body: {
          openai: { configured: true, source: "env", store_available: true },
        },
      },
    });
    renderWithProviders(<SemanticSettings repositoryId="repo_1" />);

    await screen.findByText(/configured from \.env/i);
  });

  it("sends the typed key and clears the field afterwards", async () => {
    const fetchMock = stubBackend({
      "PUT /v1/credentials/openai": {
        body: {
          openai: {
            configured: true,
            source: "credential_store",
            store_available: true,
          },
        },
      },
    });
    renderWithProviders(<SemanticSettings repositoryId="repo_1" />);

    await userEvent.type(
      await screen.findByLabelText(/openai api key/i),
      "sk-typed-by-user",
    );
    await userEvent.click(screen.getByRole("button", { name: /save key/i }));

    const put = fetchMock.mock.calls.find(
      ([url, init]) =>
        String(url).includes("/v1/credentials/openai") &&
        (init as RequestInit | undefined)?.method === "PUT",
    );
    expect(put).toBeDefined();
    const body = JSON.parse(String((put?.[1] as RequestInit).body)) as Record<
      string,
      unknown
    >;
    expect(body["api_key"]).toBe("sk-typed-by-user");

    // Emptied once the key is stored: leaving it populated invites a second
    // save and keeps the secret sitting in the DOM.
    await waitFor(() =>
      expect(screen.getByLabelText(/openai api key/i)).toHaveValue(""),
    );
  });

  it("explains itself when the machine has no credential store", async () => {
    stubBackend({
      "/v1/credentials": {
        body: {
          openai: { configured: false, source: null, store_available: false },
        },
      },
    });
    renderWithProviders(<SemanticSettings repositoryId="repo_1" />);

    await screen.findByText(/credential store is unavailable/i);
  });
});
