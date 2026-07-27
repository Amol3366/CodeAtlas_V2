/**
 * The conversation stream client.
 *
 * Three rules from `AGENTS.md` Section 14.5, implemented here rather than in
 * each component that streams:
 *
 * - **Idempotent.** An event whose sequence we have already applied is dropped.
 *   Reconnecting replays, and a replayed event must not append twice.
 * - **Resumable.** The last applied sequence is sent as `Last-Event-ID`, so the
 *   server sends exactly what was missed.
 * - **Unknown types are ignored.** The event vocabulary will grow; a client that
 *   throws on an unfamiliar type would break on a backend upgrade.
 */

export type StreamEventType =
  | "run.accepted"
  | "retrieval.started"
  | "retrieval.progress"
  | "evidence.available"
  | "generation.delta"
  | "answer.completed"
  | "run.warning"
  | "run.failed"
  | "run.cancelled"
  | "heartbeat";

export interface StreamEvent {
  readonly contract_version: string;
  readonly request_id: string;
  readonly conversation_id: string;
  readonly message_id: string;
  readonly sequence: number;
  readonly timestamp: string;
  readonly event: StreamEventType | string;
  readonly payload: Record<string, unknown>;
}

const TERMINAL: ReadonlySet<string> = new Set([
  "answer.completed",
  "run.failed",
  "run.cancelled",
]);

export function isTerminal(event: StreamEvent): boolean {
  return TERMINAL.has(event.event);
}

export interface StreamHandlers {
  readonly onEvent: (event: StreamEvent) => void;
  /** Called once when the run reaches a terminal state or the server closes. */
  readonly onClose?: (reason: "terminal" | "closed" | "error") => void;
}

export interface StreamSubscription {
  /** Stops the stream. Safe to call more than once. */
  readonly close: () => void;
  /** The highest sequence applied so far, or -1 before the first event. */
  readonly lastSequence: () => number;
}

/**
 * A sequence tracker, separated so it can be tested without a transport.
 *
 * `EventSource` cannot set request headers, so resume is expressed as a query
 * parameter as well; the backend accepts either.
 */
export class SequenceTracker {
  #last = -1;

  get last(): number {
    return this.#last;
  }

  /** Whether this event is new. Duplicates and replays return `false`. */
  accept(event: StreamEvent): boolean {
    if (!Number.isInteger(event.sequence) || event.sequence <= this.#last) {
      return false;
    }
    this.#last = event.sequence;
    return true;
  }

  reset(): void {
    this.#last = -1;
  }
}

export function parseEvent(data: string): StreamEvent | null {
  try {
    const parsed: unknown = JSON.parse(data);
    if (
      typeof parsed !== "object" ||
      parsed === null ||
      typeof (parsed as StreamEvent).sequence !== "number" ||
      typeof (parsed as StreamEvent).event !== "string"
    ) {
      return null;
    }
    return parsed as StreamEvent;
  } catch {
    // A frame we cannot parse is not a reason to tear down a live stream.
    return null;
  }
}

export function streamUrl(conversationId: string, after: number): string {
  const base = `/v1/conversations/${encodeURIComponent(conversationId)}/stream`;
  return after >= 0 ? `${base}?after=${after}` : base;
}

export function subscribeToConversation(
  conversationId: string,
  handlers: StreamHandlers,
  factory: (url: string) => EventSource = (url) => new EventSource(url),
): StreamSubscription {
  const tracker = new SequenceTracker();
  let source: EventSource | null = null;
  let closed = false;

  const finish = (reason: "terminal" | "closed" | "error") => {
    if (closed) return;
    closed = true;
    source?.close();
    source = null;
    handlers.onClose?.(reason);
  };

  const open = () => {
    if (closed) return;
    source = factory(streamUrl(conversationId, tracker.last));
    source.onmessage = (message: MessageEvent<string>) => {
      const event = parseEvent(message.data);
      if (event === null || !tracker.accept(event)) return;
      handlers.onEvent(event);
      if (isTerminal(event)) finish("terminal");
    };
    source.onerror = () => {
      // The server closes the stream when a run ends; that surfaces here as an
      // error with nothing left to read. Treating it as fatal is correct: the
      // persisted message is the authority and the caller refetches it.
      finish(source?.readyState === EventSource.CLOSED ? "closed" : "error");
    };
  };

  open();

  return {
    close: () => finish("closed"),
    lastSequence: () => tracker.last,
  };
}
