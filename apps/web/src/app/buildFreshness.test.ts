import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  buildAssetSignature,
  extractBuildAssetPaths,
  useReloadOnNewBuild,
} from "./buildFreshness";

describe("build freshness", () => {
  it("extracts the hashed Vite assets from an application shell", () => {
    const paths = extractBuildAssetPaths(`
      <!doctype html>
      <script type="module" src="/assets/index-new.js"></script>
      <link rel="stylesheet" href="/assets/index-new.css">
      <script src="https://example.test/not-ours.js"></script>
    `);

    expect(paths).toEqual(["/assets/index-new.css", "/assets/index-new.js"]);
  });

  it("creates a stable signature independent of duplicate order", () => {
    expect(
      buildAssetSignature([
        "/assets/index-new.js",
        "/assets/index-new.css",
        "/assets/index-new.js",
      ]),
    ).toBe("/assets/index-new.css\n/assets/index-new.js");
  });

  it("ignores a dev shell without built asset hashes", () => {
    expect(
      buildAssetSignature(
        extractBuildAssetPaths(`
          <!doctype html>
          <script type="module" src="/src/main.tsx"></script>
        `),
      ),
    ).toBe("");
  });
});

/**
 * The hook itself, which had no coverage at all.
 *
 * Everything that decides whether a stale tab reloads lives here, so a defect
 * in it is invisible to the three tests above — they only exercise the two pure
 * helpers it happens to call.
 */
describe("useReloadOnNewBuild", () => {
  const RELOADED_SIGNATURE_KEY = "codeatlas.reloadedBuildSignature";
  let reload: ReturnType<typeof vi.fn>;

  /** The bundle this tab is currently executing. */
  function currentlyServing(asset: string): void {
    document.head.innerHTML = `<script type="module" src="${asset}"></script>`;
  }

  /** What the server answers for `/` — i.e. the build now on disk. */
  function serverAnswers(asset: string): void {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        text: async () =>
          `<!doctype html><html><head><script type="module" src="${asset}"></script></head><body></body></html>`,
      }),
    );
  }

  function wrapper({ children }: { children: ReactNode }) {
    return createElement(MemoryRouter, null, children);
  }

  beforeEach(() => {
    reload = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: {
        origin: "http://localhost:3000",
        pathname: "/",
        search: "",
        reload,
      },
    });
    window.sessionStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    document.head.innerHTML = "";
    window.sessionStorage.clear();
  });

  it("reloads when the server is serving a newer build", async () => {
    currentlyServing("/assets/index-old.js");
    serverAnswers("/assets/index-new.js");

    renderHook(() => useReloadOnNewBuild(), { wrapper });

    await waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
  });

  it("does not reload when the served build is the one already running", async () => {
    currentlyServing("/assets/index-same.js");
    serverAnswers("/assets/index-same.js");

    renderHook(() => useReloadOnNewBuild(), { wrapper });

    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(reload).not.toHaveBeenCalled();
  });

  it("clears the loop guard once the running build matches the server", async () => {
    currentlyServing("/assets/index-same.js");
    serverAnswers("/assets/index-same.js");
    window.sessionStorage.setItem(RELOADED_SIGNATURE_KEY, "/assets/index-same.js");

    renderHook(() => useReloadOnNewBuild(), { wrapper });

    await waitFor(() =>
      expect(window.sessionStorage.getItem(RELOADED_SIGNATURE_KEY)).toBeNull(),
    );
  });

  it("still reloads when a previous session left its loop guard behind", async () => {
    // The guard exists to stop a reload loop *within* a page load. But
    // sessionStorage survives browser session restore, so a guard written by a
    // reload that never completed comes back with the restored tab — and would
    // suppress the very reload the hook exists to perform. A tab running an old
    // bundle must reload regardless of what a previous session recorded.
    currentlyServing("/assets/index-old.js");
    serverAnswers("/assets/index-new.js");
    window.sessionStorage.setItem(RELOADED_SIGNATURE_KEY, "/assets/index-new.js");

    renderHook(() => useReloadOnNewBuild(), { wrapper });

    await waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
  });

  it("does not reload twice for a build that a reload just failed to apply", async () => {
    // The guard's actual purpose, and the thing the freshness window must not
    // cost us: if a reload does not resolve the mismatch, reloading again would
    // loop forever. A record written moments ago is real evidence of that.
    currentlyServing("/assets/index-old.js");
    serverAnswers("/assets/index-new.js");
    window.sessionStorage.setItem(
      RELOADED_SIGNATURE_KEY,
      JSON.stringify({ signature: "/assets/index-new.js", at: Date.now() }),
    );

    renderHook(() => useReloadOnNewBuild(), { wrapper });

    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(reload).not.toHaveBeenCalled();
  });

  it("ignores a guard whose clock is in the future rather than trusting it", async () => {
    // A suppressed reload is the harmful failure, so an impossible timestamp
    // expires rather than being believed.
    currentlyServing("/assets/index-old.js");
    serverAnswers("/assets/index-new.js");
    window.sessionStorage.setItem(
      RELOADED_SIGNATURE_KEY,
      JSON.stringify({
        signature: "/assets/index-new.js",
        at: Date.now() + 60_000,
      }),
    );

    renderHook(() => useReloadOnNewBuild(), { wrapper });

    await waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
  });

  it("does nothing in a dev shell with no hashed assets", async () => {
    currentlyServing("/src/main.tsx");
    serverAnswers("/assets/index-new.js");

    renderHook(() => useReloadOnNewBuild(), { wrapper });

    expect(fetch).not.toHaveBeenCalled();
    expect(reload).not.toHaveBeenCalled();
  });
});
