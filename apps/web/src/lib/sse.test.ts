import { describe, expect, it, vi } from "vitest";

import {
  STREAM_EVENT_TYPES,
  SequenceTracker,
  isTerminal,
  parseEvent,
  streamUrl,
  subscribeToConversation,
  type StreamEvent,
} from "./sse";

function event(overrides: Partial<StreamEvent> = {}): StreamEvent {
  return {
    contract_version: "1.0",
    request_id: "req_1",
    conversation_id: "conv_1",
    message_id: "msg_2",
    sequence: 0,
    timestamp: "2026-07-27T12:00:00+00:00",
    event: "retrieval.started",
    payload: {},
    ...overrides,
  };
}

/**
 * A minimal EventSource stand-in; the real one needs a network.
 *
 * It dispatches by event *name*, which is the detail that matters. An earlier
 * version called `onmessage` for every frame, so the client appeared to work
 * while it could not have received a single real frame: the server names every
 * event, and a named event never reaches `onmessage`. A fake that is more
 * permissive than the real thing tests nothing.
 */
class FakeEventSource {
  static readonly CLOSED = 2;
  onmessage: ((message: MessageEvent<string>) => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 1;
  closed = false;
  readonly listeners = new Map<string, Set<EventListener>>();

  constructor(readonly url: string) {}

  addEventListener(type: string, listener: EventListener): void {
    const existing = this.listeners.get(type) ?? new Set<EventListener>();
    existing.add(listener);
    this.listeners.set(type, existing);
  }

  /** Deliver one frame under its own event name, as the browser would. */
  emit(payload: StreamEvent): void {
    const message = {
      data: JSON.stringify(payload),
    } as MessageEvent<string>;
    for (const listener of this.listeners.get(payload.event) ?? []) {
      listener(message as unknown as Event);
    }
  }

  /** Deliver a named frame that carries no sequenced payload. */
  emitNamed(type: string, data: string): void {
    const message = { data } as MessageEvent<string>;
    for (const listener of this.listeners.get(type) ?? []) {
      listener(message as unknown as Event);
    }
  }

  close(): void {
    this.closed = true;
    this.readyState = 2;
  }
}

describe("SequenceTracker", () => {
  it("accepts increasing sequences", () => {
    const tracker = new SequenceTracker();

    expect(tracker.accept(event({ sequence: 0 }))).toBe(true);
    expect(tracker.accept(event({ sequence: 1 }))).toBe(true);
    expect(tracker.last).toBe(1);
  });

  it("drops a duplicate", () => {
    const tracker = new SequenceTracker();
    tracker.accept(event({ sequence: 0 }));

    expect(tracker.accept(event({ sequence: 0 }))).toBe(false);
  });

  it("drops a replayed earlier event", () => {
    // Reconnecting replays; applying an old event again would duplicate text.
    const tracker = new SequenceTracker();
    tracker.accept(event({ sequence: 5 }));

    expect(tracker.accept(event({ sequence: 3 }))).toBe(false);
    expect(tracker.last).toBe(5);
  });

  it("starts before the first sequence so event zero is new", () => {
    expect(new SequenceTracker().last).toBe(-1);
  });
});

describe("parseEvent", () => {
  it("parses a well-formed frame", () => {
    expect(parseEvent(JSON.stringify(event()))?.sequence).toBe(0);
  });

  it("returns null for malformed json rather than throwing", () => {
    // A frame we cannot read must not tear down a live stream.
    expect(parseEvent("{not json")).toBeNull();
  });

  it("returns null when required fields are missing", () => {
    expect(parseEvent(JSON.stringify({ hello: "world" }))).toBeNull();
  });
});

describe("isTerminal", () => {
  it("treats every terminal kind as terminal", () => {
    // A client waiting only for answer.completed would hang on a failed run.
    expect(isTerminal(event({ event: "answer.completed" }))).toBe(true);
    expect(isTerminal(event({ event: "run.failed" }))).toBe(true);
    expect(isTerminal(event({ event: "run.cancelled" }))).toBe(true);
  });

  it("does not treat progress or heartbeat as terminal", () => {
    expect(isTerminal(event({ event: "heartbeat" }))).toBe(false);
    expect(isTerminal(event({ event: "retrieval.progress" }))).toBe(false);
  });

  it("does not treat an unknown future type as terminal", () => {
    expect(isTerminal(event({ event: "something.new" }))).toBe(false);
  });
});

describe("streamUrl", () => {
  it("omits the resume parameter before the first event", () => {
    expect(streamUrl("conv_1", -1)).toBe("/v1/conversations/conv_1/stream");
  });

  it("carries the last applied sequence when resuming", () => {
    expect(streamUrl("conv_1", 7)).toBe(
      "/v1/conversations/conv_1/stream?after=7",
    );
  });

  it("encodes the conversation id", () => {
    expect(streamUrl("a/b", -1)).toContain("a%2Fb");
  });
});

describe("subscribeToConversation", () => {
  it("delivers events in order and stops at a terminal event", () => {
    let source: FakeEventSource | null = null;
    const onEvent = vi.fn();
    const onClose = vi.fn();

    subscribeToConversation(
      "conv_1",
      { onEvent, onClose },
      (url) => (source = new FakeEventSource(url)) as unknown as EventSource,
    );

    const fake = source as unknown as FakeEventSource;
    fake.emit(event({ sequence: 0, event: "run.accepted" }));
    fake.emit(event({ sequence: 1, event: "answer.completed" }));

    expect(onEvent).toHaveBeenCalledTimes(2);
    expect(onClose).toHaveBeenCalledWith("terminal");
    expect(fake.closed).toBe(true);
  });

  it("ignores duplicates delivered after a reconnect", () => {
    let source: FakeEventSource | null = null;
    const onEvent = vi.fn();

    subscribeToConversation(
      "conv_1",
      { onEvent },
      (url) => (source = new FakeEventSource(url)) as unknown as EventSource,
    );

    const fake = source as unknown as FakeEventSource;
    fake.emit(event({ sequence: 0 }));
    fake.emit(event({ sequence: 0 }));
    fake.emit(event({ sequence: 1 }));

    expect(onEvent).toHaveBeenCalledTimes(2);
  });

  it("ignores an event type it has never heard of", () => {
    // Section 11.2: clients must safely ignore unknown future event types.
    // With named SSE frames that happens at the transport — no listener is
    // registered, so nothing is delivered and nothing throws. It also cannot
    // advance the sequence, so a reconnect replays it and it is ignored again.
    let source: FakeEventSource | null = null;
    const onEvent = vi.fn();

    const subscription = subscribeToConversation(
      "conv_1",
      { onEvent },
      (url) => (source = new FakeEventSource(url)) as unknown as EventSource,
    );

    (source as unknown as FakeEventSource).emit(
      event({ sequence: 0, event: "something.new" }),
    );

    expect(onEvent).not.toHaveBeenCalled();
    expect(subscription.lastSequence()).toBe(-1);
  });

  it("subscribes to every named event the server can send", () => {
    // A frame named by the server reaches only a listener registered for that
    // name. Missing one would silently drop that event type forever.
    let source: FakeEventSource | null = null;

    subscribeToConversation(
      "conv_1",
      { onEvent: vi.fn() },
      (url) => (source = new FakeEventSource(url)) as unknown as EventSource,
    );

    const fake = source as unknown as FakeEventSource;
    for (const type of STREAM_EVENT_TYPES) {
      expect(fake.listeners.has(type)).toBe(true);
    }
  });

  it("treats the server's stream.closed directive as a clean close", () => {
    // Sent when no run is live: the persisted message is the answer, so the
    // caller must stop waiting and go read it.
    let source: FakeEventSource | null = null;
    const onEvent = vi.fn();
    const onClose = vi.fn();

    subscribeToConversation(
      "conv_1",
      { onEvent, onClose },
      (url) => (source = new FakeEventSource(url)) as unknown as EventSource,
    );

    (source as unknown as FakeEventSource).emitNamed(
      "stream.closed",
      '{"reason":"no_active_run","action":"fetch_final_message"}',
    );

    expect(onClose).toHaveBeenCalledWith("closed");
    expect(onEvent).not.toHaveBeenCalled();
  });

  it("closes only once even when asked twice", () => {
    let source: FakeEventSource | null = null;
    const onClose = vi.fn();

    const subscription = subscribeToConversation(
      "conv_1",
      { onEvent: vi.fn(), onClose },
      (url) => (source = new FakeEventSource(url)) as unknown as EventSource,
    );

    subscription.close();
    subscription.close();

    expect(onClose).toHaveBeenCalledTimes(1);
    expect((source as unknown as FakeEventSource).closed).toBe(true);
  });

  it("reports the last applied sequence for a caller that resumes", () => {
    let source: FakeEventSource | null = null;

    const subscription = subscribeToConversation(
      "conv_1",
      { onEvent: vi.fn() },
      (url) => (source = new FakeEventSource(url)) as unknown as EventSource,
    );

    (source as unknown as FakeEventSource).emit(event({ sequence: 4 }));

    expect(subscription.lastSequence()).toBe(4);
  });
});
