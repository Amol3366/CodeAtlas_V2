# Design — CodeAtlas

Status: current as of 2026-08-06

The implemented source of truth is `apps/web/src/styles/tokens.css`. This file
documents that system and the rules around it. **If the two disagree, the
tokens file wins** — and this file should be updated in the same change.

Tokens are stored as bare HSL triples so Tailwind v4's `@theme inline` can wrap
them and so opacity modifiers work. Hex values below are the rendered
equivalents, for eyeballing only.

## Principles

1. **Restrained neutrals, one accent.** Color carries meaning here — freshness,
   confidence, severity — so decorative color competes with signal.
2. **Color is never the only signal.** Every status also carries a label or an
   icon. Color alone fails for a colorblind reader and in high-contrast modes.
3. **WCAG 2.2 AA is a release requirement**, not a polish pass — contrast,
   keyboard, focus, labels, screen readers.
4. **Skeletons only for real pending data.** Never fake progress, never fake an
   analysis result.

## Colors — Light

| Token | HSL | ≈ Hex | Use |
| --- | --- | --- | --- |
| `--surface` | `0 0% 100%` | `#FFFFFF` | Page background |
| `--surface-raised` | `220 14% 98%` | `#F9FAFB` | Cards, sidebar, composer |
| `--surface-sunken` | `220 14% 96%` | `#F3F4F6` | Code excerpts, wells |
| `--border` | `220 13% 88%` | `#DCDFE4` | 1px hairlines |
| `--text` | `222 20% 12%` | `#191C25` | Body and headings |
| `--text-muted` | `220 9% 42%` | `#616875` | Metadata, timestamps, captions |
| `--accent` | `231 62% 48%` | `#2E45C7` | Primary action, links, focus ring |
| `--accent-contrast` | `0 0% 100%` | `#FFFFFF` | Text on accent |
| `--status-fresh` | `152 55% 32%` | `#257E4F` | Fresh snapshot, success |
| `--status-stale` | `38 88% 38%` | `#B64A0C` | Stale/partial freshness, warning |
| `--status-error` | `0 65% 44%` | `#B92727` | Failure, high severity |
| `--status-info` | `214 60% 42%` | `#2B62AB` | Neutral notice, limitations |

## Colors — Dark

Applied by `[data-theme="dark"]` on the root, set by the theme provider from the
stored preference or the system setting. A media query alone could not express
an explicit user override, which is why the attribute exists.

| Token | HSL | ≈ Hex |
| --- | --- | --- |
| `--surface` | `224 20% 9%` | `#12151C` |
| `--surface-raised` | `224 18% 13%` | `#1B1F28` |
| `--surface-sunken` | `224 22% 7%` | `#0E1116` |
| `--border` | `223 14% 24%` | `#353A46` |
| `--text` | `220 18% 94%` | `#EFF1F5` |
| `--text-muted` | `220 10% 68%` | `#A4AAB6` |
| `--accent` | `231 74% 70%` | `#7A8BEB` |
| `--accent-contrast` | `224 20% 9%` | `#12151C` |
| `--status-fresh` | `152 45% 58%` | `#68C293` |
| `--status-stale` | `38 80% 62%` | `#EDB44A` |
| `--status-error` | `0 70% 68%` | `#E87373` |
| `--status-info` | `214 70% 70%` | `#79A8E5` |

Status hues stay constant across themes; only lightness and saturation move, so
"stale" reads as the same idea in both.

## Typography

Font stack — system, no webfont, no network request:

```
ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif
```

Code uses the monospace system stack. `-webkit-font-smoothing: antialiased` on
body.

| Role | Size | Weight | Notes |
| --- | --- | --- | --- |
| H1 | 1.5rem / 24px | 600 | Page and route titles |
| H2 | 1.25rem / 20px | 600 | Answer sections |
| H3 | 1rem / 16px | 600 | Evidence group headers |
| Body | 1rem / 16px | 400 | 1.6 line-height |
| Small | 0.875rem / 14px | 400 | Metadata, snapshot labels |
| Code | 0.8125rem / 13px | 400 | Excerpts, paths, symbol names |

`--measure: 46rem` is the comfortable reading width for prose. **Structured
reports may exceed it** — a change-analysis table should not be squeezed into a
paragraph column.

## Spacing

`--space-1` through `--space-8`: `0.25 / 0.5 / 0.75 / 1 / 1.5 / 2 rem`
(4, 8, 12, 16, 24, 32 px). Stay on the scale.

## Radius, Shadow, Motion

```
--radius-sm  0.25rem   inputs, chips, badges
--radius-md  0.5rem    buttons, cards
--radius-lg  0.75rem   dialogs, drawers, sheets

--shadow-sm  0 1px 2px  hsl(222 20% 12% / 0.06)   raised surfaces
--shadow-md  0 4px 12px hsl(222 20% 12% / 0.10)   overlays only

--motion-fast  120ms   hover, focus, small state
--motion-base  200ms   drawer, sheet, dialog
```

Dark theme shadows switch to pure black at higher alpha (`0.4` / `0.5`), because
a tinted shadow is invisible on a dark surface.

`@media (prefers-reduced-motion: reduce)` forces all animation and transition
durations to `0.01ms` and `scroll-behavior: auto`. Motion is a preference, not a
decoration.

## Components

- **Buttons** — `--radius-md`, 2.5rem (40px) height, `--space-4` horizontal
  padding. Primary is accent on `--accent-contrast`; secondary is
  `--surface-raised` with a border; ghost is transparent until hover.
- **Inputs and the composer** — `--radius-md`, 2.5rem min height, 1px border,
  multiline auto-grow on the composer.
- **Cards** — `--radius-lg`, 1px border, `--surface-raised`, `--shadow-sm`. No
  heavy elevation.
- **Focus ring** — a global rule puts `2px solid hsl(var(--accent))` with
  `2px` offset on `:focus-visible` for every link, button, input, textarea,
  select, and `[tabindex]`. Do not remove it locally.
- **Status chips** (freshness, derivation, severity) — small caps-height text
  plus an icon plus the status color. **The text is mandatory.**
- **Inline citations** — `[n]` markers rendered in the answer text are buttons.
  Activating one opens that evidence. There is no duplicated evidence list and
  no chip row beneath the answer; the marker is the only affordance, so the
  answer reads as prose rather than as prose followed by a bibliography.
- **Evidence drawer** — right rail on desktop, overlay on medium, full-height
  sheet on mobile. Shows path, symbol, line range, derivation, confidence, and
  the snapshot label, over a `--surface-sunken` syntax-highlighted excerpt with
  the cited lines emphasized. It **mounts only once a citation is chosen** —
  nothing is fetched or rendered for an answer whose evidence nobody opened.
- **Settings provider panels** - the Settings route uses summary panels,
  provider cards, status badges, connection/coverage panels, and inline
  provider actions. Embedding and answer provider configuration are visually
  grouped but kept operational: saving settings and testing a provider are
  distinct actions with their own loading and error states. A provider card
  that is *selected but unavailable* must stay visible and legible rather than
  taking the disabled treatment — a user who cannot see their own selection
  cannot correct it.

  Settings does **not** download models. Where a model must be fetched, the
  panel names it and shows the `ollama pull …` command to run in a terminal.

## Layout

Three coordinated desktop regions: left sidebar (repository selector, freshness
indicator, conversation history grouped by relative date), main conversation
(sticky compact header, centered readable column, sticky composer), and the
evidence rail.

Medium screens collapse the rail to an overlay. Mobile makes the sidebar and the
evidence drawer separate full-height sheets.

Settings is a full route, not a modal. It keeps the same restrained surfaces as
the rest of the app, but uses a denser operations layout: current state at the
top, provider choice next, then diagnostics and actions. Provider cards should
scan quickly without looking like marketing cards.

## Non-Negotiables for UI Work

- Never use color alone for freshness, confidence, severity, or error state.
- Never render repository content without sanitizing — no injected HTML,
  scripts, styles, event handlers, or instructions.
- Never show a skeleton for data that is not actually pending.
- Never render cached Settings provider controls before the route has refetched
  the current settings and model catalog after mount.
- Never display a canned repository answer or fake analysis progress.
- Every interactive state needs loading, empty, success, error, retry, keyboard,
  and responsive handling before the change is done.
