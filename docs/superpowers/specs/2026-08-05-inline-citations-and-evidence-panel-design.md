# Inline citations and an on-demand evidence panel

Date: 2026-08-05
Status: approved by the user, not yet planned or implemented
Related: ADR-0006 (web application design), `documentation/design.md`

## Problem

Two complaints, both about the answer view.

**Citations are rendered three times.** For one answer a user currently sees:

1. each claim ending in plain-text markers — `- PaymentService.capture calls … [1]`;
2. a plain-text `**Evidence**` numbered list with paths, ranges, derivation, and
   confidence, emitted by `render_answer` (`conversations/templates.py:106`);
3. a row of clickable chips repeating the same citations
   (`features/conversations/Thread.tsx:164`).

The markers that sit where the fact is are not clickable, and the thing that is
clickable sits at the bottom, after a wall of lines. The interaction is
therefore furthest from the text it belongs to.

**The evidence rail occupies space before it has anything to show.** At ≥1280px
the shell grid is `[280px_1fr_380px]` and the `aside` renders
`hidden xl:block` when no citation is selected (`app/Shell.tsx:124`), so an
empty 380px column is reserved from the moment the page loads.

## Decisions

| Question | Decision |
| --- | --- |
| Where do citations appear? | Inline, as buttons, at the end of the fact they support |
| What remains below the answer? | Nothing — the inline buttons are the only citation UI |
| When does the panel exist? | Only after a citation is clicked |
| Where does it come from? | Slides in from the right, over the conversation |

## Design

### 1. Inline citation buttons

A new `AnswerBody` component renders the answer markdown and replaces each `[n]`
marker with a `<button>` that opens evidence `n`. The ordinal mapping already
exists: every `MessageEvidence` carries `citation_ordinal`.

The visible label stays `[1]` so the answer text is not disrupted. The
accessible name carries what the removed list used to show:

> `Evidence 1: src/payments/service.py lines 6-6, static_resolved`

This matters beyond accessibility. `documentation/rules.md` requires
`derivation` and `confidence` to remain visible rather than collapse into a
single score, and the plain-text list was the only place they appeared at a
glance. Putting them in the accessible name and the tooltip keeps them
reachable without restoring the wall of lines.

A marker with no matching evidence renders as plain text. A dead button that
opens nothing would be worse than the marker it replaced.

### 2. Removing the duplicates

- `render_answer` stops emitting the `**Evidence**` block. Claims keep their
  `[n]` markers, which are now the interactive element.
- The chip row in `Thread.tsx` is deleted.
- The `**Warnings**` and `**Limitations**` blocks are unchanged.

`render_answer` is used only by `conversations/pipeline.py:219`, so CLI output,
Markdown reports, and SARIF are unaffected.

**Historical answers are not rewritten.** A persisted answer is the record of
what CodeAtlas said, and `tests/fixtures/upgrade/schema_0008.json` shows stored
message content containing the old `**Evidence**` block. Those messages keep
their text and render it as ordinary markdown. Only new answers change.

### 3. The evidence panel

The `xl` grid becomes `[280px_1fr]`. The `aside` renders nothing while no
citation is selected, so the conversation uses the full width.

On selection the panel mounts as a fixed, right-anchored overlay at every
breakpoint and slides in from the right over `--motion-base` (200ms).
`tokens.css` already forces animation to `0.01ms` under
`prefers-reduced-motion`, so the transition inherits that without new code.

The drawer's internals are untouched: focus moves to the close button on open
and returns to the opener on close, Escape closes, and the query, states, and
markup stay as they are.

### 4. Testing

**Component** — a `[1]` marker renders as a button; clicking it opens that
evidence; an unmatched marker stays plain text; no chip row exists; the panel
is absent before a click and present after; the accessible name carries path,
line range, and derivation. Existing `vitest-axe` assertions must still pass.

**Python** — `tests/unit/test_answer_templates.py` asserts the `**Evidence**`
block is gone and the `[n]` markers remain.

No test is deleted, skipped, or weakened.

## Out of scope

- The drawer's internal layout, fetching, and states.
- A collapsed "all evidence" section. Explicitly declined: the user asked for
  inline-only. It is the natural retrofit if scanning paths without clicking
  turns out to matter.
- Rewriting persisted answers.
- Streaming and SSE behaviour.

## Compatibility

No contract change. `contract_version` stays `1.1`. No migration, no REST
change, no new dependency. The evidence model, `citation_ordinal`, and the
drawer's API are all unchanged.

The visible text of *new* answers changes, which is a product change rather
than a contract one: the answer body has always been prose derived from
structured findings, and the structured findings are untouched.
