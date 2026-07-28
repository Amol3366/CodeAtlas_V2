import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { RenderResult } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";

/**
 * Renders a component with the providers it needs and a cache that never
 * retries — a test asserting an error state should see it immediately rather
 * than after a backoff.
 */
export function renderWithProviders(
  ui: ReactElement,
  {
    route = "/",
    path = "*",
  }: {
    route?: string;
    /**
     * The route pattern the component is mounted under. `useParams` reads from
     * a matched route, so a component that expects `:conversationId` sees
     * nothing without one — the entry alone is not enough.
     */
    path?: string;
  } = {},
): RenderResult {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });

  function Wrapper({ children }: { readonly children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[route]}>
          <Routes>
            <Route path={path} element={children} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );
  }

  return render(ui, { wrapper: Wrapper });
}

export interface StubbedRoute {
  readonly status?: number;
  readonly body: unknown;
}

/**
 * A `fetch` stand-in answering from a `"METHOD /path"` table.
 *
 * An unstubbed route answers 500 rather than throwing, so a test that forgot a
 * route fails on the assertion it cares about instead of on a transport error.
 */
export function stubFetch(routes: Record<string, StubbedRoute>) {
  const handler = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const match = routes[`${method} ${url}`] ?? routes[url];
    if (match === undefined) {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            error: {
              code: "NOT_STUBBED",
              message: `No stub for ${method} ${url}`,
              request_id: "req_test",
              retryable: false,
            },
          }),
          { status: 500, headers: { "Content-Type": "application/json" } },
        ),
      );
    }
    return Promise.resolve(
      new Response(JSON.stringify(match.body), {
        status: match.status ?? 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });
  vi.stubGlobal("fetch", handler);
  return handler;
}

export function apiError(code: string, message: string, retryable = false) {
  return {
    error: { code, message, request_id: "req_test", retryable },
  };
}

/**
 * A stand-in for `EventSource`, which jsdom does not implement.
 *
 * Since P6-STREAM the thread opens a stream after every submission, so without
 * this any test that sends a message dies on `EventSource is not defined` —
 * pointing at the transport instead of at whatever the test was asserting.
 *
 * It models *named* dispatch, which is the part that matters: the server names
 * every frame, and a fake that delivered everything to `onmessage` would let a
 * client that only listens there pass here and receive nothing in a browser.
 * That is exactly the defect P6-01 found.
 */
export class FakeEventSource {
  static readonly instances: FakeEventSource[] = [];
  static readonly CLOSED = 2;

  readonly url: string;
  readyState = 1;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: (() => void) | null = null;
  readonly #listeners = new Map<string, Set<EventListener>>();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: EventListener): void {
    const existing = this.#listeners.get(type) ?? new Set<EventListener>();
    existing.add(listener);
    this.#listeners.set(type, existing);
  }

  removeEventListener(type: string, listener: EventListener): void {
    this.#listeners.get(type)?.delete(listener);
  }

  close(): void {
    this.readyState = FakeEventSource.CLOSED;
  }

  /** Deliver one named frame, as the server sends it. */
  emit(type: string, data: unknown): void {
    const event = new MessageEvent("message", { data: JSON.stringify(data) });
    for (const listener of this.#listeners.get(type) ?? []) {
      listener(event as unknown as Event);
    }
  }
}

/** Install the fake for the duration of a test. Returns the instance list. */
export function stubEventSource(): readonly FakeEventSource[] {
  FakeEventSource.instances.length = 0;
  vi.stubGlobal("EventSource", FakeEventSource);
  return FakeEventSource.instances;
}
