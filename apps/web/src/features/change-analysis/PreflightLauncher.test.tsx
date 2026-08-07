import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";

import { PreflightLauncher } from "./PreflightLauncher";

function renderWithClient(element: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{element}</QueryClientProvider>,
  );
}

describe("PreflightLauncher", () => {
  it("disables running without a repository and says why", () => {
    renderWithClient(
      <PreflightLauncher repositoryId={null} onAnalysed={vi.fn()} />,
    );

    expect(
      screen.getByRole("button", { name: /run preflight/i }),
    ).toBeDisabled();
    expect(screen.getByText(/select a repository/i)).toBeInTheDocument();
  });

  it("defaults the working-tree base to HEAD", () => {
    renderWithClient(
      <PreflightLauncher repositoryId="r1" onAnalysed={vi.fn()} />,
    );

    expect(screen.getByLabelText(/base ref/i)).toHaveValue("HEAD");
  });

  it("offers a commit range as well as the working tree", async () => {
    renderWithClient(
      <PreflightLauncher repositoryId="r1" onAnalysed={vi.fn()} />,
    );

    await userEvent.click(screen.getByRole("radio", { name: /commit range/i }));

    // A range needs two distinct commits; the working tree compares against
    // HEAD itself, so the defaults must move when the mode does.
    expect(screen.getByLabelText(/base ref/i)).toHaveValue("HEAD~1");
    expect(screen.getByLabelText(/target ref/i)).toHaveValue("HEAD");
  });

  it("does not offer a target ref in working-tree mode", () => {
    renderWithClient(
      <PreflightLauncher repositoryId="r1" onAnalysed={vi.fn()} />,
    );

    expect(screen.queryByLabelText(/target ref/i)).not.toBeInTheDocument();
  });
});
