import { QueryClient } from "@tanstack/react-query";

// The server is the source of truth for history and message status
// (`AGENTS.md` Section 14.5). The cache exists to keep the UI responsive, so
// it is short-lived and never authoritative.
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      retry: (failureCount, error) => {
        // Only a transient failure is worth retrying; a 4xx means the request
        // was wrong and repeating it would just be wrong again.
        const retryable =
          typeof error === "object" &&
          error !== null &&
          "retryable" in error &&
          (error as { retryable: boolean }).retryable;
        return retryable === true && failureCount < 2;
      },
    },
  },
});
