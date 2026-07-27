import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Markdown } from "./Markdown";

/**
 * Repository content is data, in the browser exactly as on the server. These
 * tests are the ones that would matter most if they were missing: each asserts
 * that a specific injection vector renders as inert text rather than as
 * behavior.
 */
describe("Markdown", () => {
  it("renders ordinary markdown", () => {
    render(<Markdown>{"**bold** and `code`"}</Markdown>);

    expect(screen.getByText("bold").tagName).toBe("STRONG");
    expect(screen.getByText("code").tagName).toBe("CODE");
  });

  it("never executes a script tag", () => {
    const { container } = render(
      <Markdown>{"before <script>window.pwned = true</script> after"}</Markdown>,
    );

    expect(container.querySelector("script")).toBeNull();
    expect((window as unknown as Record<string, unknown>).pwned).toBeUndefined();
  });

  it("strips raw html rather than rendering it", () => {
    const { container } = render(
      <Markdown>{'<div class="injected">markup</div>'}</Markdown>,
    );

    expect(container.querySelector(".injected")).toBeNull();
  });

  it("removes inline event handlers", () => {
    const { container } = render(
      <Markdown>{'<img src="x" onerror="window.pwned = true" />'}</Markdown>,
    );

    expect(container.querySelector("img")).toBeNull();
    expect((window as unknown as Record<string, unknown>).pwned).toBeUndefined();
  });

  it("refuses a javascript: link", () => {
    const { container } = render(
      <Markdown>{"[click me](javascript:window.pwned=true)"}</Markdown>,
    );

    const link = container.querySelector("a");
    expect(link?.getAttribute("href") ?? "").not.toContain("javascript:");
  });

  it("refuses a data: link", () => {
    const { container } = render(
      <Markdown>{"[x](data:text/html;base64,PHNjcmlwdD4=)"}</Markdown>,
    );

    const link = container.querySelector("a");
    expect(link?.getAttribute("href") ?? "").not.toContain("data:");
  });

  it("allows an http link but never lets it reach the opener", () => {
    const { container } = render(
      <Markdown>{"[docs](https://example.invalid/guide)"}</Markdown>,
    );

    const link = container.querySelector("a");
    expect(link?.getAttribute("href")).toBe("https://example.invalid/guide");
    expect(link?.getAttribute("rel")).toContain("noopener");
  });

  it("does not render a style tag", () => {
    const { container } = render(
      <Markdown>{"<style>body { display: none }</style>"}</Markdown>,
    );

    expect(container.querySelector("style")).toBeNull();
  });

  it("renders a fenced code block as text", () => {
    render(<Markdown>{"```\n<script>alert(1)</script>\n```"}</Markdown>);

    expect(screen.getByText(/<script>alert\(1\)<\/script>/)).toBeInTheDocument();
  });

  it("renders an iframe as nothing", () => {
    const { container } = render(
      <Markdown>{'<iframe src="https://evil.invalid"></iframe>'}</Markdown>,
    );

    expect(container.querySelector("iframe")).toBeNull();
  });
});
