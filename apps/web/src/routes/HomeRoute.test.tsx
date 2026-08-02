import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ActiveRepositoryContext } from "../app/context";
import { renderWithProviders, stubFetch } from "../test/harness";
import { HomeRoute } from "./HomeRoute";

function renderHome(repositoryId: string | null) {
  return renderWithProviders(
    <ActiveRepositoryContext.Provider
      value={{ repositoryId, setRepositoryId: vi.fn() }}
    >
      <HomeRoute />
    </ActiveRepositoryContext.Provider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("HomeRoute", () => {
  it("opens in chat space when no repository is selected", () => {
    stubFetch({});

    renderHome(null);

    expect(
      screen.getByRole("heading", { name: "No repository selected" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Repositories" })).toHaveAttribute(
      "href",
      "/repositories",
    );
    expect(screen.queryByLabelText("Add local repository")).not.toBeInTheDocument();
  });

  it("asks the user to index explicitly when the selected repository has no snapshot", async () => {
    stubFetch({
      "/v1/repositories/repo_1/status": {
        body: {
          repository_id: "repo_1",
          snapshot: null,
          file_count: 0,
          symbol_count: 0,
          parse_error_count: 0,
          warnings: [],
        },
      },
      "/v1/conversations?repository_id=repo_1": {
        body: { items: [], next_cursor: null },
      },
    });

    renderHome("repo_1");

    expect(
      await screen.findByRole("heading", { name: "Index this repository" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Repositories" })).toHaveAttribute(
      "href",
      "/repositories",
    );
  });

  it("creates the first chat thread for an indexed repository", async () => {
    const handler = stubFetch({
      "/v1/repositories/repo_1/status": {
        body: {
          repository_id: "repo_1",
          snapshot: {
            snapshot_id: "snap_1",
            git_head: null,
            working_tree_fingerprint: "fp",
            freshness: "fresh",
            semantic_coverage: 0,
          },
          file_count: 1,
          symbol_count: 1,
          parse_error_count: 0,
          warnings: [],
        },
      },
      "/v1/conversations?repository_id=repo_1": {
        body: { items: [], next_cursor: null },
      },
      "POST /v1/conversations": {
        status: 201,
        body: {
          conversation_id: "conv_new",
          repository_id: "repo_1",
          title: "New conversation",
          created_at: "2026-07-27T12:00:00Z",
          updated_at: "2026-07-27T12:00:00Z",
          last_message_at: null,
          archived_at: null,
        },
      },
    });

    renderHome("repo_1");

    await waitFor(() => {
      expect(
        handler.mock.calls.some(
          (call) =>
            String(call[0]) === "/v1/conversations" &&
            (call[1] as RequestInit | undefined)?.method === "POST",
        ),
      ).toBe(true);
    });
  });
});
