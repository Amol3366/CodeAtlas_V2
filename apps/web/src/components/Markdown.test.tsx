import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

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

/**
 * Citation markers are the interaction, not decoration.
 *
 * The answer body states a fact and ends it with `[1]`. That marker is where a
 * reader's attention already is, so it is what must be clickable — which means
 * turning text into an element without ever letting repository text become
 * markup.
 */
describe("Markdown citations", () => {
  it("replaces a marker with the rendered citation", () => {
    render(
      <Markdown renderCitation={(ordinal) => <button>cite {ordinal}</button>}>
        {"A fact about the code. [1]"}
      </Markdown>,
    );

    expect(screen.getByRole("button", { name: "cite 1" })).toBeInTheDocument();
    expect(screen.queryByText(/\[1\]/)).not.toBeInTheDocument();
  });

  it("keeps the marker as text when the renderer declines it", () => {
    render(<Markdown renderCitation={() => null}>{"A fact. [7]"}</Markdown>);

    expect(screen.getByText(/\[7\]/)).toBeInTheDocument();
  });

  it("renders every marker in one paragraph", () => {
    render(
      <Markdown renderCitation={(ordinal) => <button>cite {ordinal}</button>}>
        {"A fact. [1][2]"}
      </Markdown>,
    );

    expect(screen.getByRole("button", { name: "cite 1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "cite 2" })).toBeInTheDocument();
  });

  it("leaves a marker inside code untouched", () => {
    const renderCitation = vi.fn(() => <button>cite</button>);
    render(
      <Markdown renderCitation={renderCitation}>
        {"Use `array[1]` carefully."}
      </Markdown>,
    );

    expect(renderCitation).not.toHaveBeenCalled();
  });

  it("renders normally without the prop", () => {
    render(<Markdown>{"Plain text. [1]"}</Markdown>);

    expect(screen.getByText(/\[1\]/)).toBeInTheDocument();
  });

  it("keeps the same citation element across a re-render", () => {
    // Focus lives on a DOM node. If a re-render replaces the node, anything
    // holding a reference to it — the evidence panel's focus-return, for
    // instance — is left pointing at a detached element, and the user lands on
    // the document body instead of the citation they opened.
    // A stable renderer, as the real caller provides: identity churn there is
    // itself a remount trigger, and this test is about what Markdown does with
    // props that have not changed.
    const renderCitation = (ordinal: number) => <button>cite {ordinal}</button>;

    function Harness({ tick }: { readonly tick: number }) {
      return (
        <div data-tick={tick}>
          <Markdown renderCitation={renderCitation}>{"A fact. [1]"}</Markdown>
        </div>
      );
    }

    const { rerender } = render(<Harness tick={1} />);
    const before = screen.getByRole("button", { name: "cite 1" });
    before.focus();

    rerender(<Harness tick={2} />);

    const after = screen.getByRole("button", { name: "cite 1" });
    expect(after).toBe(before);
    expect(after).toHaveFocus();
  });
});
