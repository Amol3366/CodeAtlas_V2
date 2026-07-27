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

export interface MarkdownProps {
  readonly children: string;
  readonly className?: string;
}

export function Markdown({ children, className }: MarkdownProps) {
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
