import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { groupByRecency } from "../../lib/conversations";
import type { Conversation } from "../../lib/conversations";
import { apiError, renderWithProviders, stubFetch } from "../../test/harness";
import { Sidebar } from "./Sidebar";

function conversation(overrides: Partial<Conversation> = {}): Conversation {
  return {
    conversation_id: "conv_1",
    repository_id: "repo_1",
    title: "What changed?",
    created_at: "2026-07-27T12:00:00Z",
    updated_at: "2026-07-27T12:00:00Z",
    last_message_at: "2026-07-27T12:00:00Z",
    archived_at: null,
    ...overrides,
  };
}

const listUrl = "/v1/conversations?repository_id=repo_1";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("groupByRecency", () => {
  const now = new Date("2026-07-27T15:00:00Z");

  it("labels a conversation from today", () => {
    const groups = groupByRecency(
      [conversation({ last_message_at: "2026-07-27T09:00:00Z" })],
      now,
    );
    expect(groups[0]?.[0]).toBe("Today");
  });

  it("labels older conversations by distance", () => {
    const groups = groupByRecency(
      [
        conversation({ conversation_id: "a", last_message_at: "2026-07-26T09:00:00Z" }),
        conversation({ conversation_id: "b", last_message_at: "2026-07-24T09:00:00Z" }),
        conversation({ conversation_id: "c", last_message_at: "2026-05-01T09:00:00Z" }),
      ],
      now,
    );
    expect(groups.map(([label]) => label)).toEqual([
      "Yesterday",
      "Previous 7 days",
      "Older",
    ]);
  });

  it("falls back to created_at when a thread has no messages", () => {
    const groups = groupByRecency(
      [conversation({ last_message_at: null, created_at: "2026-07-27T09:00:00Z" })],
      now,
    );
    expect(groups[0]?.[0]).toBe("Today");
  });

  it("keeps the order the server returned within a group", () => {
    // The backend orders by activity; re-sorting here could disagree with the
    // cursor and make paging inconsistent.
    const groups = groupByRecency(
      [
        conversation({ conversation_id: "first", title: "first" }),
        conversation({ conversation_id: "second", title: "second" }),
      ],
      now,
    );
    expect(groups[0]?.[1].map((item) => item.title)).toEqual([
      "first",
      "second",
    ]);
  });
});

describe("Sidebar", () => {
  it("asks for a repository before listing anything", () => {
    stubFetch({});
    renderWithProviders(<Sidebar repositoryId={null} />);
    expect(screen.getByText(/Select a repository/i)).toBeInTheDocument();
  });

  it("lists conversations grouped by recency", async () => {
    stubFetch({
      [listUrl]: { body: { items: [conversation()], next_cursor: null } },
    });

    renderWithProviders(<Sidebar repositoryId="repo_1" />);

    expect(await screen.findByText("What changed?")).toBeInTheDocument();
  });

  it("filters by title", async () => {
    const user = userEvent.setup();
    stubFetch({
      [listUrl]: {
        body: {
          items: [
            conversation({ conversation_id: "a", title: "capture impact" }),
            conversation({ conversation_id: "b", title: "unrelated" }),
          ],
          next_cursor: null,
        },
      },
    });

    renderWithProviders(<Sidebar repositoryId="repo_1" />);
    await screen.findByText("capture impact");
    await user.type(screen.getByLabelText("Search conversations"), "capture");

    expect(screen.getByText("capture impact")).toBeInTheDocument();
    expect(screen.queryByText("unrelated")).not.toBeInTheDocument();
  });

  it("says when a search matches nothing rather than showing an empty list", async () => {
    const user = userEvent.setup();
    stubFetch({
      [listUrl]: { body: { items: [conversation()], next_cursor: null } },
    });

    renderWithProviders(<Sidebar repositoryId="repo_1" />);
    await screen.findByText("What changed?");
    await user.type(screen.getByLabelText("Search conversations"), "zzz");

    expect(screen.getByText("No matching conversations.")).toBeInTheDocument();
  });

  it("marks the conversation named in the URL as current", async () => {
    stubFetch({
      [listUrl]: { body: { items: [conversation()], next_cursor: null } },
    });

    renderWithProviders(<Sidebar repositoryId="repo_1" />, {
      route: "/conversations/conv_1",
      path: "/conversations/:conversationId",
    });

    // The URL identifies the active thread (Section 14.5); the sidebar reads
    // it rather than keeping its own idea of what is selected.
    await waitFor(() => {
      expect(screen.getByText("What changed?")).toHaveAttribute(
        "aria-current",
        "page",
      );
    });
  });

  it("creates a conversation and navigates to it", async () => {
    const user = userEvent.setup();
    const handler = stubFetch({
      [listUrl]: { body: { items: [], next_cursor: null } },
      "POST /v1/conversations": {
        status: 201,
        body: conversation({ conversation_id: "conv_new" }),
      },
    });

    renderWithProviders(<Sidebar repositoryId="repo_1" />);
    await user.click(await screen.findByRole("button", { name: "New chat" }));

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

  it("renames a conversation", async () => {
    const user = userEvent.setup();
    const handler = stubFetch({
      [listUrl]: { body: { items: [conversation()], next_cursor: null } },
      "PATCH /v1/conversations/conv_1": { body: conversation({ title: "Renamed" }) },
    });

    renderWithProviders(<Sidebar repositoryId="repo_1" />);
    await user.click(
      await screen.findByRole("button", { name: "Rename What changed?" }),
    );
    await user.clear(screen.getByLabelText("New title"));
    await user.type(screen.getByLabelText("New title"), "Renamed{Enter}");

    await waitFor(() => {
      expect(
        handler.mock.calls.some(
          (call) => (call[1] as RequestInit | undefined)?.method === "PATCH",
        ),
      ).toBe(true);
    });
  });

  it("archives a conversation", async () => {
    const user = userEvent.setup();
    const handler = stubFetch({
      [listUrl]: { body: { items: [conversation()], next_cursor: null } },
      "PATCH /v1/conversations/conv_1": { body: conversation() },
    });

    renderWithProviders(<Sidebar repositoryId="repo_1" />);
    await user.click(
      await screen.findByRole("button", { name: "Archive What changed?" }),
    );

    await waitFor(() => {
      expect(
        handler.mock.calls.some((call) =>
          JSON.stringify((call[1] as RequestInit | undefined)?.body ?? "").includes(
            "archived",
          ),
        ),
      ).toBe(true);
    });
  });

  it("confirms before deleting and says the deletion is recoverable", async () => {
    const user = userEvent.setup();
    const confirm = vi.fn(() => true);
    vi.stubGlobal("confirm", confirm);
    const handler = stubFetch({
      [listUrl]: { body: { items: [conversation()], next_cursor: null } },
      "DELETE /v1/conversations/conv_1": { status: 204, body: null },
    });

    renderWithProviders(<Sidebar repositoryId="repo_1" />);
    await user.click(
      await screen.findByRole("button", { name: "Delete What changed?" }),
    );

    expect(confirm).toHaveBeenCalledWith(
      expect.stringContaining("recovered"),
    );
    await waitFor(() => {
      expect(
        handler.mock.calls.some(
          (call) => (call[1] as RequestInit | undefined)?.method === "DELETE",
        ),
      ).toBe(true);
    });
  });

  it("does not delete when the confirmation is declined", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("confirm", vi.fn(() => false));
    const handler = stubFetch({
      [listUrl]: { body: { items: [conversation()], next_cursor: null } },
    });

    renderWithProviders(<Sidebar repositoryId="repo_1" />);
    await user.click(
      await screen.findByRole("button", { name: "Delete What changed?" }),
    );

    expect(
      handler.mock.calls.some(
        (call) => (call[1] as RequestInit | undefined)?.method === "DELETE",
      ),
    ).toBe(false);
  });

  it("shows the error envelope when listing fails", async () => {
    stubFetch({
      [listUrl]: {
        status: 404,
        body: apiError("REPOSITORY_NOT_FOUND", "No repository matches that ID."),
      },
    });

    renderWithProviders(<Sidebar repositoryId="repo_1" />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "REPOSITORY_NOT_FOUND",
    );
  });
});
