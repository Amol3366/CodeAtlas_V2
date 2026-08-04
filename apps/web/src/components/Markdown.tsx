import { Children, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import type { Options as SanitizeSchema } from "rehype-sanitize";

/**
 * Renders assistant text as Markdown, sanitized.
 *
 * Every string that reaches this component originated in a repository, and a
 * repository is untrusted input (`AGENTS.md` Section 4.4). The schema below is
 * an allowlist: raw HTML is never parsed, only these tags survive, and the only
 * link protocols permitted are ones that cannot execute.
 *
 * The backend already escapes repository values into code spans before storing
 * an answer. This is the second layer, and it is not redundant: the backend
 * protects what it wrote, and this protects what the browser renders — including
 * text that arrives from any future source.
 */
const schema: SanitizeSchema = {
  ...defaultSchema,
  tagNames: [
    "p",
    "br",
    "strong",
    "em",
    "code",
    "pre",
    "ul",
    "ol",
    "li",
    "blockquote",
    "h1",
    "h2",
    "h3",
    "h4",
    "hr",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "a",
  ],
  attributes: {
    a: ["href", "title"],
    code: ["className"],
    th: ["align"],
    td: ["align"],
  },
  // No `javascript:`, no `data:` — a link is for reading, never for running.
  protocols: { href: ["http", "https", "mailto"] },
  // Raw HTML never enters the tree in the first place; this is belt and braces.
  clobber: [],
};

const CITATION = /\[(\d+)\]/g;

/**
 * Replace `[n]` markers in text with whatever the caller renders for them.
 *
 * Walks rendered children rather than the raw Markdown source, so a marker
 * inside a code span or fenced block is never touched: those arrive as
 * elements, not as bare strings, and only strings are split. That distinction
 * is what keeps quoted repository source — `array[1]` — from being rewritten.
 */
function withCitations(
  children: ReactNode,
  renderCitation: (ordinal: number) => ReactNode,
): ReactNode {
  return Children.map(children, (child) => {
    if (typeof child !== "string") return child;

    const parts: ReactNode[] = [];
    let cursor = 0;
    for (const match of child.matchAll(CITATION)) {
      const start = match.index ?? 0;
      const rendered = renderCitation(Number(match[1]));
      if (rendered === null || rendered === undefined) continue;
      if (start > cursor) parts.push(child.slice(cursor, start));
      parts.push(rendered);
      cursor = start + match[0].length;
    }
    if (parts.length === 0) return child;
    if (cursor < child.length) parts.push(child.slice(cursor));
    return parts;
  });
}

export interface MarkdownProps {
  readonly children: string;
  readonly className?: string;
  /**
   * Render a `[n]` citation marker. Returning null keeps the literal text,
   * which is what an ordinal with no matching evidence must do — a button that
   * opens nothing is worse than the marker it replaced.
   */
  readonly renderCitation?: (ordinal: number) => ReactNode;
}

export function Markdown({
  children,
  className,
  renderCitation,
}: MarkdownProps) {
  const wrap = (nodes: ReactNode): ReactNode =>
    renderCitation === undefined ? nodes : withCitations(nodes, renderCitation);
  return (
    <div
      className={className}
      data-testid="markdown"
      // `prose`-like spacing is applied through tokens rather than a plugin so
      // the reading measure stays under our control.
      style={{ maxWidth: "var(--measure)" }}
    >
      <ReactMarkdown
        // `rehype-raw` is deliberately absent: without it, raw HTML in the
        // source is already inert text rather than markup.
        rehypePlugins={[[rehypeSanitize, schema]]}
        components={{
          p: ({ children: content }) => <p>{wrap(content)}</p>,
          li: ({ children: content }) => <li>{wrap(content)}</li>,
          td: ({ children: content }) => <td>{wrap(content)}</td>,
          th: ({ children: content }) => <th>{wrap(content)}</th>,
          a: ({ href, children: linkChildren, ...rest }) => (
            <a
              {...rest}
              href={href}
              // An external link must not hand the opener a window handle.
              rel="noopener noreferrer nofollow"
              target="_blank"
            >
              {linkChildren}
            </a>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
