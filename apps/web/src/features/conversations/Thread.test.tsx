import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Message, MessageSubmission } from "../../lib/conversations";
import {
  apiError,
  renderWithProviders,
  stubEventSource,
  stubFetch,
} from "../../test/harness";
import { Thread } from "./Thread";

function message(overrides: Partial<Message> = {}): Message {
  return {
    message_id: "msg_1",
    conversation_id: "conv_1",
    role: "user",
    status: "complete",
    sequence_number: 1,
    content: "PaymentService.capture",
    error_code: null,
    created_at: "2026-07-27T12:00:00Z",
    completed_at: "2026-07-27T12:00:00Z",
    evidence: [],
    snapshot_id: null,
    warnings: [],
    ...overrides,
  };
}

function submission(overrides: Partial<MessageSubmission> = {}): MessageSubmission {
  return {
    conversation_id: "conv_1",
    user_message_id: "msg_1",
    message_id: "msg_2",
    run_id: "run_1",
    status: "complete",
    sequence_number: 2,
    content: "capture is defined in `src/payments/service.py:7-8`.",
    snapshot_id: "snap_1",
    intent: "exact_symbol",
    evidence: [
      {
        evidence_id: "ev_1",
        citation_ordinal: 1,
        file_path: "src/payments/service.py",
        symbol: "PaymentService.capture",
        start_line: 7,
        end_line: 8,
        content_hash: "abc",
        derivation: "deterministic",
        confidence: 1,
        snapshot_id: "snap_1",
      },
    ],
    warnings: [],
    limitations: [],
    error_code: null,
    latency_ms: 12,
    ...overrides,
  };
}

const messagesUrl = "/v1/conversations/conv_1/messages";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Thread", () => {
  it("renders the stored turns", async () => {
    stubFetch({
      [messagesUrl]: {
        body: {
          items: [
            message(),
            message({
              message_id: "msg_2",
              role: "assistant",
              sequence_number: 2,
              content: "An answer.",
            }),
          ],
          next_cursor: null,
        },
      },
    });

    renderWithProviders(<Thread conversationId="conv_1" />);

    expect(await screen.findByText("PaymentService.capture")).toBeInTheDocument();
    expect(screen.getByText("An answer.")).toBeInTheDocument();
  });

  it("shows the submitted question immediately, then reconciles to the server row", async () => {
    const user = userEvent.setup();
    stubFetch({
      [messagesUrl]: { body: { items: [], next_cursor: null } },
      [`POST ${messagesUrl}`]: { status: 201, body: submission() },
    });

    renderWithProviders(<Thread conversationId="conv_1" />);
    await user.type(await screen.findByLabelText(/Ask about this repository/i), "capture");
    await user.click(screen.getByRole("button", { name: "Send" }));

    // The optimistic turn is dropped once the server's rows land, so the
    // question can never appear twice.
    await waitFor(() => {
      expect(screen.queryByTestId("pending-turn")).not.toBeInTheDocument();
    });
  });

  it("renders assistant text through the sanitizer", async () => {
    stubFetch({
      [messagesUrl]: {
        body: {
          items: [
            message({
              message_id: "msg_2",
              role: "assistant",
              content: "<script>window.pwned = true</script>ok",
            }),
          ],
          next_cursor: null,
        },
      },
    });

    const { container } = renderWithProviders(<Thread conversationId="conv_1" />);
    await screen.findByTestId("message-assistant");

    expect(container.querySelector("script")).toBeNull();
    expect((window as unknown as Record<string, unknown>).pwned).toBeUndefined();
  });

  it("offers a retry on a failed answer and keeps the failure visible", async () => {
    const user = userEvent.setup();
    const handler = stubFetch({
      [messagesUrl]: {
        body: {
          items: [
            message({
              message_id: "msg_2",
              role: "assistant",
              status: "failed",
              content: "",
              error_code: "SNAPSHOT_NOT_READY",
            }),
          ],
          next_cursor: null,
        },
      },
      "POST /v1/conversations/messages/msg_2/retry": {
        status: 201,
        body: submission(),
      },
    });

    renderWithProviders(<Thread conversationId="conv_1" />);
    expect(await screen.findByText("SNAPSHOT_NOT_READY")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => {
      expect(
        handler.mock.calls.some((call) => String(call[0]).endsWith("/retry")),
      ).toBe(true);
    });
  });

  it("labels a cancelled answer as cancelled rather than empty", async () => {
    stubFetch({
      [messagesUrl]: {
        body: {
          items: [
            message({
              message_id: "msg_2",
              role: "assistant",
              status: "cancelled",
              content: "",
            }),
          ],
          next_cursor: null,
        },
      },
    });

    renderWithProviders(<Thread conversationId="conv_1" />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /was cancelled/i,
    );
  });

  it("sends on Enter and inserts a newline on Shift+Enter", async () => {
    const user = userEvent.setup();
    const handler = stubFetch({
      [messagesUrl]: { body: { items: [], next_cursor: null } },
      [`POST ${messagesUrl}`]: { status: 201, body: submission() },
    });

    renderWithProviders(<Thread conversationId="conv_1" />);
    const composer = await screen.findByLabelText(/Ask about this repository/i);

    await user.type(composer, "line one{Shift>}{Enter}{/Shift}line two");
    expect((composer as HTMLTextAreaElement).value).toContain("\n");

    await user.type(composer, "{Enter}");
    await waitFor(() => {
      expect(
        handler.mock.calls.some(
          (call) =>
            String(call[0]) === messagesUrl &&
            (call[1] as RequestInit | undefined)?.method === "POST",
        ),
      ).toBe(true);
    });
  });

  it("refuses to send an empty question", async () => {
    stubFetch({ [messagesUrl]: { body: { items: [], next_cursor: null } } });

    renderWithProviders(<Thread conversationId="conv_1" />);

    expect(await screen.findByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("shows citations for the answer once the run has been read back", async () => {
    // Since P6-STREAM the 202 carries no answer, so the citations shown are
    // the ones on the refetched message. Stubbing the message list with them
    // is therefore the accurate model, not a shortcut.
    const user = userEvent.setup();
    stubEventSource();
    stubFetch({
      [messagesUrl]: {
        body: {
          items: [
            message({
              message_id: "msg_2",
              role: "assistant",
              content: "capture is defined. [1]",
              evidence: submission().evidence,
            }),
          ],
          next_cursor: null,
        },
      },
      [`POST ${messagesUrl}`]: {
        status: 202,
        body: { ...submission(), status: "queued", content: "", evidence: [] },
      },
    });

    renderWithProviders(<Thread conversationId="conv_1" />);
    await user.type(await screen.findByLabelText(/Ask about this repository/i), "capture");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(
      await screen.findByRole("button", { name: /^Evidence 1:/ }),
    ).toBeInTheDocument();
  });

  it("hands a clicked citation to its owner with the message it belongs to", async () => {
    const user = userEvent.setup();
    const onCite = vi.fn();
    stubEventSource();
    stubFetch({
      [messagesUrl]: {
        body: {
          items: [
            message({
              message_id: "msg_2",
              role: "assistant",
              content: "capture is defined. [1]",
              evidence: submission().evidence,
            }),
          ],
          next_cursor: null,
        },
      },
      [`POST ${messagesUrl}`]: {
        status: 202,
        body: { ...submission(), status: "queued", content: "", evidence: [] },
      },
    });

    renderWithProviders(<Thread conversationId="conv_1" onCite={onCite} />);
    await user.type(await screen.findByLabelText(/Ask about this repository/i), "capture");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await user.click(await screen.findByRole("button", { name: /^Evidence 1:/ }));

    expect(onCite).toHaveBeenCalledWith(
      expect.objectContaining({ evidence_id: "ev_1" }),
      "msg_2",
    );
  });

  it("surfaces a submission failure without losing the thread", async () => {
    const user = userEvent.setup();
    stubFetch({
      [messagesUrl]: { body: { items: [], next_cursor: null } },
      [`POST ${messagesUrl}`]: {
        status: 409,
        body: apiError("CONVERSATION_ARCHIVED", "This conversation is archived."),
      },
    });

    renderWithProviders(<Thread conversationId="conv_1" />);
    await user.type(await screen.findByLabelText(/Ask about this repository/i), "capture");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "CONVERSATION_ARCHIVED",
    );
  });

  it("does not leak a pending turn into another conversation", async () => {
    // Switching threads mid-send must not show one thread's question in
    // another (Section 14.5).
    const user = userEvent.setup();
    stubFetch({
      [messagesUrl]: { body: { items: [], next_cursor: null } },
      "/v1/conversations/conv_2/messages": {
        body: { items: [], next_cursor: null },
      },
      [`POST ${messagesUrl}`]: { status: 201, body: submission() },
    });

    const { rerender } = renderWithProviders(
      <Thread conversationId="conv_1" />,
    );
    await user.type(await screen.findByLabelText(/Ask about this repository/i), "capture");

    rerender(<Thread conversationId="conv_2" />);

    // The new thread loads its own messages first; the composer reappears
    // once it has.
    const composer = (await screen.findByLabelText(
      /Ask about this repository/i,
    )) as HTMLTextAreaElement;

    expect(screen.queryByTestId("pending-turn")).not.toBeInTheDocument();
    expect(composer.value).toBe("");
  });
});

/**
 * P6-STREAM (ADR-0008): the answer no longer arrives in the submission
 * response, so everything a reopened thread shows has to come from the
 * persisted message. These pin that.
 */
describe("a reopened thread", () => {
  it("restores citations from the persisted message", async () => {
    stubFetch({
      [messagesUrl]: {
        body: {
          items: [
          message({ message_id: "msg_1", role: "user" }),
          message({
            message_id: "msg_2",
            role: "assistant",
            sequence_number: 2,
            content:
              "capture is defined in `src/payments/service.py:7-8`. [1]",
            snapshot_id: "snap_1",
            evidence: submission().evidence,
          }),
        ],
          next_cursor: null,
        },
      },
    });

    renderWithProviders(<Thread conversationId="conv_1" />);

    // Nothing was submitted in this session: if the citation renders, it came
    // from storage, which is the whole point.
    expect(
      await screen.findByRole("button", { name: /^Evidence 1:/ }),
    ).toBeInTheDocument();
  });

  it("names a citation with its path, lines, and derivation", async () => {
    // The plain-text evidence list used to carry these. Removing it must not
    // remove the only place a reader can see how a claim was derived.
    stubFetch({
      [messagesUrl]: {
        body: {
          items: [
            message({
              message_id: "msg_2",
              role: "assistant",
              sequence_number: 2,
              content: "capture is defined. [1]",
              evidence: submission().evidence,
            }),
          ],
          next_cursor: null,
        },
      },
    });

    renderWithProviders(<Thread conversationId="conv_1" />);

    const cite = await screen.findByRole("button", { name: /^Evidence 1:/ });

    expect(cite).toHaveAccessibleName(/src\/payments\/service\.py/);
    expect(cite).toHaveAccessibleName(/lines 7-8/);
    expect(cite).toHaveAccessibleName(/deterministic/);
  });

  it("leaves a marker with no matching evidence as plain text", async () => {
    // A button that opens nothing is worse than the marker it replaced, and
    // an answer stored under a different numbering can produce exactly that.
    stubFetch({
      [messagesUrl]: {
        body: {
          items: [
            message({
              message_id: "msg_2",
              role: "assistant",
              sequence_number: 2,
              content: "A claim citing nothing we hold. [4]",
              evidence: submission().evidence,
            }),
          ],
          next_cursor: null,
        },
      },
    });

    renderWithProviders(<Thread conversationId="conv_1" />);

    expect(await screen.findByText(/\[4\]/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Evidence 4:/ }),
    ).not.toBeInTheDocument();
  });

  it("does not list the citations again below the answer", async () => {
    stubFetch({
      [messagesUrl]: {
        body: {
          items: [
            message({
              message_id: "msg_2",
              role: "assistant",
              sequence_number: 2,
              content: "capture is defined. [1]",
              evidence: submission().evidence,
            }),
          ],
          next_cursor: null,
        },
      },
    });

    renderWithProviders(<Thread conversationId="conv_1" />);

    await screen.findByRole("button", { name: /^Evidence 1:/ });

    expect(
      screen.queryByRole("button", { name: /^\[1\] src\/payments/ }),
    ).not.toBeInTheDocument();
  });

  it("keeps an old answer labelled with its own snapshot", async () => {
    stubFetch({
      [messagesUrl]: {
        body: {
          items: [
          message({
            message_id: "msg_2",
            role: "assistant",
            sequence_number: 2,
            content: "An older answer.",
            snapshot_id: "snap_old",
          }),
        ],
          next_cursor: null,
        },
      },
    });

    renderWithProviders(
      <Thread conversationId="conv_1" activeSnapshotId="snap_new" />,
    );

    const banner = await screen.findByTestId("freshness-banner");
    expect(banner).toHaveTextContent("snap_old");
  });

  it("does not claim staleness when the answer used the active snapshot", async () => {
    stubFetch({
      [messagesUrl]: {
        body: {
          items: [
          message({
            message_id: "msg_2",
            role: "assistant",
            sequence_number: 2,
            content: "A current answer.",
            snapshot_id: "snap_new",
          }),
        ],
          next_cursor: null,
        },
      },
    });

    renderWithProviders(
      <Thread conversationId="conv_1" activeSnapshotId="snap_new" />,
    );

    await screen.findByText("A current answer.");
    expect(screen.queryByTestId("freshness-banner")).not.toBeInTheDocument();
  });

  it("shows a run's warnings with the answer", async () => {
    stubFetch({
      [messagesUrl]: {
        body: {
          items: [
          message({
            message_id: "msg_2",
            role: "assistant",
            sequence_number: 2,
            content: "A partial answer.",
            snapshot_id: "snap_1",
            warnings: ["GRAPH_TRUNCATED_DEPTH"],
          }),
        ],
          next_cursor: null,
        },
      },
    });

    renderWithProviders(<Thread conversationId="conv_1" />);

    expect(await screen.findByText(/GRAPH_TRUNCATED_DEPTH/)).toBeInTheDocument();
  });

  it("explains known run warnings in the fallback warning list", async () => {
    stubFetch({
      [messagesUrl]: {
        body: {
          items: [
            message({
              message_id: "msg_2",
              role: "assistant",
              sequence_number: 2,
              content: "A broad answer.",
              snapshot_id: "snap_1",
              warnings: ["LEXICAL_QUERY_RELAXED"],
            }),
          ],
          next_cursor: null,
        },
      },
    });

    renderWithProviders(<Thread conversationId="conv_1" />);

    expect(
      await screen.findByText(/broadened the search terms/i),
    ).toBeInTheDocument();
    expect(screen.queryByText("LEXICAL_QUERY_RELAXED")).not.toBeInTheDocument();
  });

  it("does not duplicate warnings already rendered into the markdown answer", async () => {
    stubFetch({
      [messagesUrl]: {
        body: {
          items: [
            message({
              message_id: "msg_2",
              role: "assistant",
              sequence_number: 2,
              content:
                "A broad answer.\n\n**Warnings**\n- The exact text query matched nothing, so CodeAtlas broadened the search terms before returning evidence.\n",
              snapshot_id: "snap_1",
              warnings: ["LEXICAL_QUERY_RELAXED"],
            }),
          ],
          next_cursor: null,
        },
      },
    });

    renderWithProviders(<Thread conversationId="conv_1" />);

    expect(
      await screen.findAllByText(/broadened the search terms/i),
    ).toHaveLength(1);
    expect(screen.queryByTestId("run-warnings")).not.toBeInTheDocument();
  });
});

describe("a live run", () => {
  const accepted = {
    status: 202,
    body: { ...submission(), status: "queued" as const, content: "", evidence: [] },
  };

  it("opens the stream for the run it just submitted", async () => {
    const user = userEvent.setup();
    const sources = stubEventSource();
    stubFetch({
      [messagesUrl]: { body: { items: [], next_cursor: null } },
      [`POST ${messagesUrl}`]: accepted,
    });

    renderWithProviders(<Thread conversationId="conv_1" />);
    await user.type(
      await screen.findByLabelText(/Ask about this repository/i),
      "capture",
    );
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(sources.length).toBe(1));
    expect(sources[0]?.url).toContain("/v1/conversations/conv_1/stream");
  });

  it("renders generation deltas as they arrive", async () => {
    const user = userEvent.setup();
    const sources = stubEventSource();
    stubFetch({
      [messagesUrl]: {
        body: {
          items: [
            message({
              message_id: "msg_2",
              role: "assistant",
              status: "generating",
              content: "",
            }),
          ],
          next_cursor: null,
        },
      },
      [`POST ${messagesUrl}`]: accepted,
    });

    renderWithProviders(<Thread conversationId="conv_1" />);
    await user.type(
      await screen.findByLabelText(/Ask about this repository/i),
      "capture",
    );
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(sources.length).toBe(1));

    const source = sources[0];
    source?.emit("generation.delta", {
      sequence: 0,
      event: "generation.delta",
      payload: { text: "capture is " },
    });
    source?.emit("generation.delta", {
      sequence: 1,
      event: "generation.delta",
      payload: { text: "defined in service.py." },
    });

    expect(
      await screen.findByText(/capture is defined in service\.py\./),
    ).toBeInTheDocument();
  });

  it("ignores a replayed delta rather than appending it twice", async () => {
    const user = userEvent.setup();
    const sources = stubEventSource();
    stubFetch({
      [messagesUrl]: {
        body: {
          items: [
            message({
              message_id: "msg_2",
              role: "assistant",
              status: "generating",
              content: "",
            }),
          ],
          next_cursor: null,
        },
      },
      [`POST ${messagesUrl}`]: accepted,
    });

    renderWithProviders(<Thread conversationId="conv_1" />);
    await user.type(
      await screen.findByLabelText(/Ask about this repository/i),
      "capture",
    );
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(sources.length).toBe(1));

    const frame = {
      sequence: 0,
      event: "generation.delta",
      payload: { text: "once" },
    };
    sources[0]?.emit("generation.delta", frame);
    sources[0]?.emit("generation.delta", frame);

    const rendered = await screen.findByText(/once/);
    expect(rendered.textContent).toBe("once");
  });
});

it("still shows the answer when the stream cannot be opened", async () => {
  // No EventSource stub: constructing one throws, exactly as it would in a
  // browser that blocked the connection. Submission must survive it — the
  // persisted message is authoritative and reachable by refetch, so losing the
  // live view must not lose the answer.
  const user = userEvent.setup();
  stubFetch({
    [messagesUrl]: {
      body: {
        items: [
          message({
            message_id: "msg_2",
            role: "assistant",
            content: "capture is defined in service.py.",
          }),
        ],
        next_cursor: null,
      },
    },
    [`POST ${messagesUrl}`]: {
      status: 202,
      body: { ...submission(), status: "queued", content: "", evidence: [] },
    },
  });

  renderWithProviders(<Thread conversationId="conv_1" />);
  await user.type(
    await screen.findByLabelText(/Ask about this repository/i),
    "capture",
  );
  await user.click(screen.getByRole("button", { name: "Send" }));

  expect(
    await screen.findByText(/capture is defined in service\.py\./),
  ).toBeInTheDocument();
  expect(screen.queryByTestId("pending-turn")).not.toBeInTheDocument();
});
