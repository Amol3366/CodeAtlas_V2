import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import { ActiveRepositoryContext } from "../app/context";
import { renderWithProviders, stubFetch } from "../test/harness";
import { SettingsRoute } from "./SettingsRoute";

/**
 * The route wrapper, not the settings form.
 *
 * Its whole job is to answer "which repository am I about to configure?" —
 * including when the answer is "none yet". This is the one screen that can send
 * repository content off the machine, so a page that silently configured
 * whichever repository context happened to hold would be the wrong default.
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

const SETTINGS = {
  repository_id: "repo_1",
  embedding_provider: "none",
  monthly_token_budget: null,
  per_run_token_budget: null,
  transmits_off_machine: false,
  updated_at: "2026-07-30T12:00:00Z",
};

const SEMANTIC_STATUS = {
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
};

function stubBackend() {
  return stubFetch({
    "/v1/repositories": {
      body: [
        {
          repository_id: "repo_1",
          display_name: "demo",
          created_at: "2026-07-27T12:00:00Z",
        },
      ],
    },
    "/v1/models": { body: MODELS },
    "/v1/settings?repository_id=repo_1": { body: SETTINGS },
    "/v1/repositories/repo_1/semantic-status": { body: SEMANTIC_STATUS },
  });
}

function renderAt(repositoryId: string | null) {
  return renderWithProviders(
    <ActiveRepositoryContext.Provider
      value={{ repositoryId, setRepositoryId: () => undefined }}
    >
      <SettingsRoute />
    </ActiveRepositoryContext.Provider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SettingsRoute", () => {
  it("sends a user with no active repository somewhere they can pick one", async () => {
    // An empty state that states a precondition without saying how to satisfy
    // it is a dead end.
    stubBackend();
    renderAt(null);

    expect(await screen.findByText(/select a repository/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /home page/i })).toHaveAttribute(
      "href",
      "/",
    );
  });

  it("names the repository it is about to configure", async () => {
    stubBackend();
    renderAt("repo_1");

    // `waitFor`, not `findBy`: the element exists on the first render carrying
    // the id fallback, so a query that resolves as soon as it appears would
    // assert against the pre-load state and pass whatever the name became.
    await waitFor(() => {
      expect(screen.getByTestId("settings-repository")).toHaveTextContent(
        "demo",
      );
    });
  });

  it("renders the provider form for that repository", async () => {
    stubBackend();
    renderAt("repo_1");

    expect(
      await screen.findByText(/semantic search is optional/i),
    ).toBeInTheDocument();
  });

  it("falls back to the id when the repository list has not arrived", async () => {
    // The name is a nicety; the identity is not. Rendering nothing while the
    // list loads would leave the page unable to say what it configures.
    stubFetch({
      "/v1/models": { body: MODELS },
      "/v1/settings?repository_id=repo_1": { body: SETTINGS },
      "/v1/repositories/repo_1/semantic-status": { body: SEMANTIC_STATUS },
    });
    renderAt("repo_1");

    expect(await screen.findByTestId("settings-repository")).toHaveTextContent(
      "repo_1",
    );
  });

  it("has no accessibility violations", async () => {
    stubBackend();
    const { container } = renderAt("repo_1");
    await screen.findByText(/semantic search is optional/i);

    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});
