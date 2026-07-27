/**
 * The API client.
 *
 * One place that knows how to talk to `/v1` and how to read the Section 12.6
 * error envelope. Callers get a typed error with a machine-readable `code`
 * rather than a string they would have to parse.
 */

export interface ApiErrorBody {
  readonly error: {
    readonly code: string;
    readonly message: string;
    readonly request_id: string;
    readonly retryable: boolean;
    readonly details?: Record<string, string>;
  };
}

export class ApiError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly status: number,
    readonly retryable: boolean,
    readonly requestId: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function toError(response: Response): Promise<ApiError> {
  let body: ApiErrorBody | null = null;
  try {
    body = (await response.json()) as ApiErrorBody;
  } catch {
    body = null;
  }
  // A response without the envelope is still a failure; inventing a code would
  // be worse than admitting the server did not name one.
  return new ApiError(
    body?.error.code ?? "INTERNAL_ERROR",
    body?.error.message ?? "The request failed.",
    response.status,
    body?.error.retryable ?? false,
    body?.error.request_id ?? "",
  );
}

export async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    throw await toError(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(
      path,
      body === undefined
        ? { method: "POST" }
        : { method: "POST", body: JSON.stringify(body) },
    ),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};
