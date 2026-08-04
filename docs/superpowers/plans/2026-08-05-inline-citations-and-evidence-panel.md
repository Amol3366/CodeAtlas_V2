# Inline Citations and On-Demand Evidence Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make each `[n]` citation marker a clickable button at the end of the fact it supports, delete the two duplicate citation listings, and stop the evidence panel occupying space before a citation is clicked.

**Architecture:** `Markdown` gains an optional `renderCitation` prop that splits text nodes on `[n]` and hands each ordinal to the caller. `Thread` supplies a renderer that returns a button opening that evidence, and drops its chip row. `render_answer` stops emitting the `**Evidence**` block. `Shell` renders the evidence `aside` only when a citation is selected, as a right-anchored overlay that slides in.

**Tech Stack:** React 18, TypeScript strict, react-markdown + rehype-sanitize, Tailwind v4 tokens, Vitest + Testing Library + vitest-axe, Python 3.12.

## Global Constraints

- No contract change. `contract_version` stays `1.1`. No migration, no REST change, no new dependency.
- TypeScript strict; no `any`. Python type hints throughout.
- Repository text is untrusted: everything still renders through `Markdown`'s sanitizer allowlist. Citation buttons are built from `MessageEvidence` fields, never from answer text.
- Styling uses existing tokens in `apps/web/src/styles/tokens.css`. No new component library.
- `documentation/design.md`: status is never carried by colour alone; `prefers-reduced-motion` is already forced to `0.01ms` by the tokens file and must not be overridden.
- Persisted answers are never rewritten. Old messages keep their stored `**Evidence**` text.
- No test may be deleted, skipped, or weakened. Never report a test as passing that was not executed.
- Commands run from the repository root: `pnpm --dir apps/web exec …`, `uv run pytest …`.

## File Structure

| File | Responsibility |
| --- | --- |
| `apps/web/src/components/Markdown.tsx` | **Modify.** Optional `renderCitation` prop; text-node splitting |
| `apps/web/src/components/Markdown.test.tsx` | **Modify or create.** Splitting behaviour in isolation |
| `apps/web/src/features/conversations/Thread.tsx` | **Modify.** Supply the renderer; delete the chip row |
| `apps/web/src/app/Shell.tsx` | **Modify.** Grid, conditional `aside`, slide-in |
| `src/codeatlas/conversations/templates.py` | **Modify.** Drop the `**Evidence**` block |
| `tests/unit/test_answer_templates.py` | **Modify.** Assert it is gone, markers remain |

---

### Task 1: Markdown renders citation markers through a callback

**Files:**
- Modify: `apps/web/src/components/Markdown.tsx`
- Test: `apps/web/src/components/Markdown.test.tsx`

**Interfaces:**
- Produces: `MarkdownProps.renderCitation?: (ordinal: number) => ReactNode`. When supplied, every `[n]` in a text node is replaced by its return value; when it returns `null`, the original `[n]` text is kept.

Splitting happens on rendered text nodes rather than on the raw string, so a
`[1]` occurring inside a fenced code block or an inline code span is left
alone — only `p`, `li`, `td`, and `th` content is processed.

- [ ] **Step 1: Write the failing test**

Create `apps/web/src/components/Markdown.test.tsx`:

```typescript
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Markdown } from "./Markdown";

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
    render(
      <Markdown renderCitation={() => null}>{"A fact. [7]"}</Markdown>,
    );

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
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pnpm --dir apps/web exec vitest run Markdown`
Expected: FAIL — `renderCitation` is not a prop, so no button is rendered.

- [ ] **Step 3: Implement the splitting**

In `apps/web/src/components/Markdown.tsx`, add the import and helper above the component:

```typescript
import { Children, isValidElement, type ReactNode } from "react";

const CITATION = /\[(\d+)\]/g;

/**
 * Replace `[n]` markers in text with whatever the caller renders for them.
 *
 * Walks rendered children rather than the raw Markdown source, so a marker
 * inside a code span or fenced block is never touched: those arrive as
 * elements, not as bare strings, and only strings are split.
 */
function withCitations(
  children: ReactNode,
  renderCitation: (ordinal: number) => ReactNode,
): ReactNode {
  return Children.map(children, (child) => {
    if (typeof child !== "string") {
      // An element's own children are left alone. Code spans are elements,
      // and rewriting inside them would corrupt quoted source.
      return child;
    }

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
```

`isValidElement` is imported for the type guard's readability; if the linter
reports it unused, remove it from the import rather than adding a suppression.

- [ ] **Step 4: Wire the prop through**

Extend `MarkdownProps`:

```typescript
export interface MarkdownProps {
  readonly children: string;
  readonly className?: string;
  /**
   * Render a `[n]` citation marker. Returning null keeps the literal text,
   * which is what an ordinal with no matching evidence must do — a button
   * that opens nothing is worse than the marker it replaced.
   */
  readonly renderCitation?: (ordinal: number) => ReactNode;
}
```

and in the component, accept it and extend the `components` map:

```typescript
export function Markdown({ children, className, renderCitation }: MarkdownProps) {
  const cite = renderCitation;
  const wrap = (nodes: ReactNode): ReactNode =>
    cite === undefined ? nodes : withCitations(nodes, cite);
```

Then add these entries alongside the existing `a` entry inside `components`:

```typescript
          p: ({ children: content }) => <p>{wrap(content)}</p>,
          li: ({ children: content }) => <li>{wrap(content)}</li>,
          td: ({ children: content }) => <td>{wrap(content)}</td>,
          th: ({ children: content }) => <th>{wrap(content)}</th>,
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pnpm --dir apps/web exec vitest run Markdown`
Expected: PASS, all five.

- [ ] **Step 6: Verify nothing else regressed**

Run: `pnpm --dir apps/web exec vitest run && pnpm --dir apps/web exec tsc --noEmit`
Expected: both exit 0.

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/components/Markdown.tsx apps/web/src/components/Markdown.test.tsx
git commit -m "feat: let Markdown render citation markers through a callback"
```

---

### Task 2: Thread renders inline citation buttons and drops the chip row

**Files:**
- Modify: `apps/web/src/features/conversations/Thread.tsx:163` (`<Markdown>` call) and `:164-179` (the chip `<ul>`)
- Test: `apps/web/src/features/conversations/Thread.test.tsx`

**Interfaces:**
- Consumes: `MarkdownProps.renderCitation` (Task 1); `MessageEvidence` from `../../lib/conversations` with `evidence_id`, `citation_ordinal`, `file_path`, `symbol`, `start_line`, `end_line`, `derivation`, `confidence`.

- [ ] **Step 1: Write the failing test**

Add to `apps/web/src/features/conversations/Thread.test.tsx`, matching the file's existing render helper and message fixtures:

```typescript
it("renders a citation marker as a button that opens that evidence", async () => {
  const onCite = vi.fn();
  renderThread({ onCite });

  const cite = await screen.findByRole("button", { name: /^Evidence 1:/ });
  await userEvent.click(cite);

  expect(onCite).toHaveBeenCalledWith(
    expect.objectContaining({ citation_ordinal: 1 }),
    expect.any(String),
  );
});

it("names a citation with its path, lines, and derivation", async () => {
  renderThread();

  const cite = await screen.findByRole("button", { name: /^Evidence 1:/ });

  expect(cite).toHaveAccessibleName(
    expect.stringContaining("src/payments/service.py"),
  );
  expect(cite).toHaveAccessibleName(expect.stringContaining("static_resolved"));
});

it("no longer lists citations again below the answer", async () => {
  renderThread();

  await screen.findByRole("button", { name: /^Evidence 1:/ });

  expect(
    screen.queryByRole("button", { name: /src\/payments\/service\.py:\d/ }),
  ).not.toBeInTheDocument();
});
```

Read the top of the test file first and reuse its existing helper name and
message fixture. If the fixture's evidence does not include
`derivation: "static_resolved"` and `file_path: "src/payments/service.py"`,
adjust the assertions to the fixture's actual values rather than changing the
fixture.

- [ ] **Step 2: Run the test to verify it fails**

Run: `pnpm --dir apps/web exec vitest run Thread`
Expected: FAIL — no button whose name starts with "Evidence 1:".

- [ ] **Step 3: Add the citation renderer**

In `Thread.tsx`, inside the component that currently renders `<Markdown>{visible}</Markdown>` and the evidence list, add above the `return`:

```typescript
  const byOrdinal = new Map(evidence.map((item) => [item.citation_ordinal, item]));

  function renderCitation(ordinal: number) {
    const item = byOrdinal.get(ordinal);
    // An ordinal with no evidence stays literal text. This is not defensive
    // padding: historical answers were stored with their own numbering, and a
    // button that opens nothing is worse than the marker it replaced.
    if (item === undefined) return null;
    const label =
      `Evidence ${ordinal}: ${item.file_path} ` +
      `lines ${item.start_line}-${item.end_line}, ${item.derivation}`;
    return (
      <button
        key={`${item.evidence_id}-${ordinal}`}
        type="button"
        onClick={() => onCite?.(item, message.message_id)}
        aria-label={label}
        title={label}
        className="mx-[2px] rounded-[var(--radius-sm)] border border-border px-[var(--space-1)] align-baseline text-xs text-accent"
      >
        [{ordinal}]
      </button>
    );
  }
```

The accessible name carries the path, the line range, and the **derivation**
because removing the plain-text list removed the only place a reader could see
how a claim was derived, and `documentation/rules.md` requires derivation to
stay visible rather than collapse into a score.

- [ ] **Step 4: Use it and delete the chip row**

Replace `<Markdown>{visible}</Markdown>` with:

```tsx
      <Markdown renderCitation={renderCitation}>{visible}</Markdown>
```

and delete the entire block that follows it:

```tsx
      {evidence.length > 0 ? (
        <ul className="mt-[var(--space-3)] flex flex-wrap gap-[var(--space-2)]">
          … chip buttons …
        </ul>
      ) : null}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pnpm --dir apps/web exec vitest run Thread`
Expected: PASS. Existing Thread tests that asserted the chip row will fail — update those assertions to the new inline buttons; do not delete the tests.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/features/conversations/Thread.tsx apps/web/src/features/conversations/Thread.test.tsx
git commit -m "feat: put citation buttons where the fact is"
```

---

### Task 3: The answer template stops repeating the evidence

**Files:**
- Modify: `src/codeatlas/conversations/templates.py:106-115`
- Test: `tests/unit/test_answer_templates.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: answer markdown containing `[n]` markers and no `**Evidence**` section.

`render_answer` is called only from `conversations/pipeline.py:219`, so CLI
output, Markdown reports, and SARIF are unaffected.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_answer_templates.py`, using the module's existing
response-building helper:

```python
def test_the_answer_does_not_repeat_its_evidence_as_a_list() -> None:
    """The citation markers are the evidence UI now.

    The list duplicated what each claim already carried, and it sat between the
    answer and the controls that act on it.
    """
    rendered = render_answer(_response(), intent=Intent.EXACT_SYMBOL)

    assert "**Evidence**" not in rendered


def test_claims_keep_their_citation_markers() -> None:
    """Removing the list must not remove the citations themselves."""
    rendered = render_answer(_response(), intent=Intent.EXACT_SYMBOL)

    assert "[1]" in rendered
```

`_response()` and `Intent.EXACT_SYMBOL` are already defined and imported in
this module; `_response()` returns one claim citing one piece of evidence.

Note that `test_a_file_path_renders_inside_a_code_span` asserts on
``` `src/payments/service.py:7-8` ``` — that string appears in the *claim*
text, not only in the removed block, so it should still pass. Verify rather
than assume, and if it fails, the claim rendering was changed by mistake.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_answer_templates.py -k evidence_as_a_list -v`
Expected: FAIL — `**Evidence**` is present.

- [ ] **Step 3: Remove the block**

Delete these lines from `render_answer`:

```python
    if response.evidence:
        lines.append("**Evidence**")
        for ordinal, item in enumerate(response.evidence, start=1):
            location = f"{item.file_path}:{item.start_line}-{item.end_line}"
            symbol = f" — `{_code(item.symbol)}`" if item.symbol else ""
            lines.append(
                f"{ordinal}. `{_code(location)}`{symbol} "
                f"({item.derivation.value}, confidence {item.confidence:.2f})"
            )
        lines.append("")
```

Leave the `citations` mapping and the claim loop that emits `[n]` exactly as
they are — they are now the only citation surface. Leave `**Warnings**` and
`**Limitations**` untouched.

Add a comment where the block was:

```python
    # The evidence list used to be repeated here. It is gone deliberately: the
    # `[n]` markers above are rendered as buttons by the web client, so the
    # list duplicated every citation in a less useful form. Persisted answers
    # written before this change keep their own text and are not rewritten.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_answer_templates.py -v`
Expected: PASS. Other tests in the file that assert on the evidence block must
be updated to the new output — update the expectation, never the assertion's
intent.

- [ ] **Step 5: Run the wider conversation suites**

Run: `uv run pytest tests/unit/test_answer_templates.py tests/integration -k "conversation or answer or pipeline" -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/codeatlas/conversations/templates.py tests/unit/test_answer_templates.py
git commit -m "feat: stop repeating evidence as a list in the answer body"
```

---

### Task 4: The evidence panel appears only when a citation is clicked

**Files:**
- Modify: `apps/web/src/app/Shell.tsx:67` (grid) and `:121-134` (the `aside`)
- Test: `apps/web/src/app/Shell.test.tsx`

**Interfaces:**
- Consumes: the existing `citation` state and `CitationContext` in `Shell.tsx`.

- [ ] **Step 1: Write the failing test**

Add to `apps/web/src/app/Shell.test.tsx`, matching its existing render helper:

```typescript
it("reserves no evidence panel before a citation is chosen", () => {
  renderShell();

  expect(
    screen.queryByRole("complementary", { name: /evidence/i }),
  ).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pnpm --dir apps/web exec vitest run Shell`
Expected: FAIL — the `aside` renders unconditionally, so the complementary
landmark is present.

- [ ] **Step 3: Narrow the grid**

Change line 67:

```tsx
        <div className="grid h-full grid-cols-1 md:grid-cols-[280px_1fr]">
```

The third track is gone: the panel is an overlay now, so reserving a column for
it would leave the space empty whenever nothing is selected — which is most of
the time.

- [ ] **Step 4: Render the panel only when selected**

Replace the whole `<aside>…</aside>` block with:

```tsx
          {citation !== null ? (
            <aside
              aria-label="Evidence"
              className="fixed inset-y-0 right-0 z-20 w-full max-w-[420px] animate-[slide-in-right_var(--motion-base)_ease-out] border-l border-border bg-surface-raised shadow-md"
            >
              <EvidenceDrawer
                evidence={citation}
                repositoryId={repositoryId}
                onClose={() => setCitation(null)}
              />
            </aside>
          ) : null}
```

- [ ] **Step 5: Add the keyframes**

In `apps/web/src/styles/tokens.css`, at the end of the file:

```css
/* The evidence panel enters from the edge it is anchored to, so the motion
   states where it came from. Reduced-motion is already handled globally: the
   rule below this file's motion tokens collapses every duration to 0.01ms. */
@keyframes slide-in-right {
  from {
    transform: translateX(100%);
  }
  to {
    transform: translateX(0);
  }
}
```

Confirm the existing `prefers-reduced-motion` block in that file targets
`animation-duration` as well as `transition-duration`. If it only covers
transitions, extend it — an animation that ignores the preference is the defect
that block exists to prevent.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pnpm --dir apps/web exec vitest run Shell`
Expected: PASS. Existing Shell tests that assert the rail is present must be
updated to click a citation first; do not delete them.

- [ ] **Step 7: Run everything**

Run: `pnpm --dir apps/web exec vitest run && pnpm --dir apps/web exec tsc --noEmit && pnpm --dir apps/web exec eslint . --max-warnings 0`
Expected: all exit 0.

- [ ] **Step 8: Commit**

```bash
git add apps/web/src/app/Shell.tsx apps/web/src/app/Shell.test.tsx apps/web/src/styles/tokens.css
git commit -m "feat: show the evidence panel only when a citation is chosen"
```

---

### Task 5: Documentation and the gate

**Files:**
- Modify: `documentation/design.md`, `docs/operations/web-application.md`, `documentation/memory.md`, `docs/plans/PLAN.md`

- [ ] **Step 1: Update the design system doc**

In `documentation/design.md`, the **Evidence drawer** bullet says it is a
"right rail on desktop". Change it to describe an overlay that exists only
while a citation is selected, entering from the right. Add a line to
**Components** describing the inline citation button and stating that its
accessible name carries path, line range, and derivation.

- [ ] **Step 2: Update the web operations doc**

In `docs/operations/web-application.md`, describe the new answer layout:
citations are buttons at the end of each claim, there is no separate evidence
list, and answers stored before this change keep their original text.

- [ ] **Step 3: Run the full gate**

Run: `powershell -ExecutionPolicy Bypass -File scripts/check_phase7.ps1 -SkipSync`
Expected: exit 0. Record the actual command, exit code, and counts. Note that
this run includes the Playwright suites; if an end-to-end spec asserts on the
old evidence list or the always-present rail, update the spec to the new
behaviour rather than skipping it.

- [ ] **Step 4: Append the handoff entry**

Append — never rewrite — an entry to `docs/plans/PLAN.md` following the Handoff
Schema: UTC timestamp, agent, transition, outcome, files, contracts (no change;
`contract_version` stays `1.1`), verification with real numbers, limitations,
next. Update `documentation/memory.md` in the same commit.

- [ ] **Step 5: Commit**

```bash
git add documentation/ docs/
git commit -m "docs: record the inline citation and evidence panel change"
```

---

## Definition of Done

- Each fact ends with clickable `[n]` buttons that open that evidence.
- No plain-text evidence list and no chip row below new answers.
- Answers stored before the change still render, with their markers inert only
  where no matching evidence exists.
- No evidence panel exists until a citation is clicked; it enters from the
  right and returns the space on close.
- `check_phase7.ps1 -SkipSync` exits 0, with the output recorded.
