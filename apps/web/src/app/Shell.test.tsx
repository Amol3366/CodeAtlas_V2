import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import { renderWithProviders, stubFetch } from "../test/harness";
import { Shell } from "./Shell";
import { ThemeProvider } from "./theme";

/**
 * Layout, landmarks, keyboard access, and the accessibility audit.
 *
 * WCAG 2.2 AA is a gate condition rather than a polish item
 * (`AGENTS.md` Section 14.4), so the audit runs here on the assembled shell,
 * not on isolated pieces where the interesting failures hide.
 */

const repository = {
  repository_id: "repo_1",
  display_name: "demo",
  created_at: "2026-07-27T12:00:00Z",
};

function stubBackend() {
  return stubFetch({
    "/v1/repositories": { body: [repository] },
    "/v1/conversations?repository_id=repo_1": {
      body: { items: [], next_cursor: null },
    },
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
    "/v1/repositories/repo_1/diagnostics": {
      body: {
        repository_id: "repo_1",
        snapshot_id: "snap_1",
        parse_error_count: 0,
        skipped_by_reason: {},
        limits: {},
        warnings: [],
      },
    },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Shell", () => {
  it("exposes the three regions as landmarks", async () => {
    stubBackend();

    renderWithProviders(
      <ThemeProvider>
        <Shell />
      </ThemeProvider>,
    );

    expect(
      await screen.findByRole("navigation", { name: "Conversations" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("main")).toBeInTheDocument();
    expect(
      screen.getByRole("complementary", { name: "Evidence" }),
    ).toBeInTheDocument();
  });

  it("has no detectable accessibility violations", async () => {
    stubBackend();

    const { container } = renderWithProviders(
      <ThemeProvider>
        <Shell />
      </ThemeProvider>,
    );
    await screen.findByRole("navigation", { name: "Conversations" });

    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });

  it("offers a keyboard-reachable disclosure for the sidebar on narrow screens", async () => {
    const user = userEvent.setup();
    stubBackend();

    renderWithProviders(
      <ThemeProvider>
        <Shell />
      </ThemeProvider>,
    );

    const disclosure = await screen.findByRole("button", {
      name: "Show conversations",
    });
    expect(disclosure).toHaveAttribute("aria-expanded", "false");
    await user.click(disclosure);
    expect(disclosure).toHaveAttribute("aria-expanded", "true");
  });

  it("offers a link to settings from the sidebar", async () => {
    // Section 14.1 puts settings in the left sidebar. It sits in the header row
    // rather than the conversation list, because that list is wrapped in a
    // navigation landmark named "Conversations" and a settings link inside it
    // would misdescribe the landmark.
    stubBackend();

    renderWithProviders(
      <ThemeProvider>
        <Shell />
      </ThemeProvider>,
    );

    const link = await screen.findByRole("link", { name: "Settings" });
    expect(link).toHaveAttribute("href", "/settings");
  });

  it("lets the theme be chosen explicitly rather than only following the system", async () => {
    const user = userEvent.setup();
    stubBackend();

    renderWithProviders(
      <ThemeProvider>
        <Shell />
      </ThemeProvider>,
    );

    const select = await screen.findByLabelText("Theme");
    await user.selectOptions(select, "dark");

    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("keeps the evidence rail out of the tab order until a citation opens it", async () => {
    stubBackend();

    renderWithProviders(
      <ThemeProvider>
        <Shell />
      </ThemeProvider>,
    );
    await screen.findByRole("navigation", { name: "Conversations" });

    // No citation is open, so the drawer renders nothing rather than an empty
    // dialog a keyboard user would have to tab through.
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
