import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createBrowserRouter, Navigate } from "react-router-dom";

import { ErrorBoundary } from "../components/ErrorBoundary";
import { Shell } from "./Shell";
import { ThemeProvider } from "./theme";
import { queryClient } from "./queryClient";
import { ConversationRoute } from "../routes/ConversationRoute";
import { HomeRoute } from "../routes/HomeRoute";

const router = createBrowserRouter([
  {
    path: "/",
    element: <Shell />,
    children: [
      { index: true, element: <HomeRoute /> },
      // The URL identifies the active conversation (Section 14.5), so a
      // reload or a shared link lands on the same thread.
      { path: "conversations/:conversationId", element: <ConversationRoute /> },
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
]);

export function App() {
  return (
    <ErrorBoundary>
      <ThemeProvider>
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </ThemeProvider>
    </ErrorBoundary>
  );
}
