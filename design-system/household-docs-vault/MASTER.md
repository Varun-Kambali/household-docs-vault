# Design system: household-docs-vault

> When building a screen, read `pages/<screen>.md` first. Its rules override this file. Otherwise follow this file exactly. Components use the semantic tokens only, never raw values. The reasons for each choice are in `docs/design-rationale.md`.

**Brief:** one person at a Mac, keyboard first, the same screens on a phone later. The screens feel calm, precise and private. They never show an answer they cannot point to on the page, never hide that the app was unsure, and never let a document vanish without a trace. They look like macOS Preview and Finder, and Things 3. They must not look like a SaaS dashboard.

## Colour

One brand hue (blue, hue 255) used for the primary action, focus, selection and citations. The neutrals are tinted toward the same hue. One accent only: the brand blue. Amber is reserved for doubt, red for danger, green for success. No colour carries meaning on its own: each state also has an icon and words.

### Light

| Token | OKLCH | Hex | Job |
|---|---|---|---|
| `--color-bg` | `oklch(0.985 0.004 250)` | `#F8FAFD` | window background |
| `--color-sidebar` | `oklch(0.965 0.006 250)` | `#F0F4F7` | sidebar (source list) |
| `--color-raised` | `oklch(0.995 0.002 250)` | `#FCFDFF` | panels: answer, inspector, dialogs |
| `--color-canvas` | `oklch(0.93 0.006 250)` | `#E5E8EC` | the grey around a page image |
| `--color-border` | `oklch(0.89 0.008 250)` | `#D7DBE0` | dividers and panel edges |
| `--color-control-border` | `oklch(0.62 0.012 250)` | `#81878D` | input and checkbox borders |
| `--color-text` | `oklch(0.22 0.015 250)` | `#151B21` | body text |
| `--color-text-muted` | `oklch(0.47 0.015 250)` | `#555C63` | secondary text, metadata |
| `--color-primary` | `oklch(0.52 0.15 255)` | `#1F68BC` | primary button, links, selection |
| `--color-on-primary` | `oklch(0.99 0.003 250)` | `#FAFCFE` | text on the primary button |
| `--color-focus` | `oklch(0.58 0.16 255)` | `#2B7AD6` | focus ring |
| `--color-doubt` | `oklch(0.50 0.11 65)` | `#8D5406` | "not sure" text and icon |
| `--color-doubt-bg` | `oklch(0.955 0.04 85)` | `#FDEFD2` | "not sure" row or note background |
| `--color-danger` | `oklch(0.52 0.17 25)` | `#B63132` | errors, destructive actions |
| `--color-success` | `oklch(0.50 0.11 150)` | `#2B7440` | done, filed |

### Dark

| Token | OKLCH | Hex |
|---|---|---|
| `--color-bg` | `oklch(0.19 0.010 250)` | `#101418` |
| `--color-sidebar` | `oklch(0.215 0.011 250)` | `#161A1E` |
| `--color-raised` | `oklch(0.245 0.012 250)` | `#1C2126` |
| `--color-canvas` | `oklch(0.155 0.008 250)` | `#0A0D10` |
| `--color-border` | `oklch(0.32 0.012 250)` | `#2E3339` |
| `--color-control-border` | `oklch(0.55 0.014 250)` | `#6C727A` |
| `--color-text` | `oklch(0.93 0.008 250)` | `#E4E8ED` |
| `--color-text-muted` | `oklch(0.72 0.012 250)` | `#9FA5AC` |
| `--color-primary` | `oklch(0.72 0.11 255)` | `#74A7E8` |
| `--color-on-primary` | `oklch(0.19 0.010 250)` | `#101418` |
| `--color-focus` | `oklch(0.74 0.12 255)` | `#75AEF5` |
| `--color-doubt` | `oklch(0.80 0.10 75)` | `#E4B572` |
| `--color-doubt-bg` | `oklch(0.30 0.05 75)` | `#3C2A0E` |
| `--color-danger` | `oklch(0.73 0.13 25)` | `#EE857E` |
| `--color-success` | `oklch(0.76 0.11 150)` | `#7CC58C` |

### Same in both modes

| Token | OKLCH | Hex | Why fixed |
|---|---|---|---|
| `--color-cite` | `oklch(0.52 0.15 255)` | `#1F68BC` | The citation box is drawn on the page image, which stays light in dark mode. 5.25:1 on white paper; the dark-mode blue would be 2.18:1. |
| `--color-cite-fill` | `oklch(0.52 0.15 255 / 0.14)` | | Fill inside the citation box, so the printed text stays readable. |

## Type

- **Text:** the system sans stack, `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif` (SF Pro on the Mac).
- **Identifiers:** the system mono stack, `ui-monospace, "SF Mono", Menlo, Consolas, monospace`, for ID, policy, account and serial numbers only.
- No web fonts and no font CDN. The app is private and must work offline.
- `font-variant-numeric: tabular-nums` on every date, amount and number column.

| Token | Size / line height | Weight | Use |
|---|---|---|---|
| `--text-caption` | 13 / 1.4 | 400 | metadata, the part labels of the "what I understood" sentence |
| `--text-body` | 16 / 1.5 | 400 | body, list rows, inputs |
| `--text-heading` | 19 / 1.3 | 600 | panel and section headings |
| `--text-title` | 23 / 1.25 | 600 | screen title (one per screen) |
| `--text-answer` | 28 / 1.2 | 600 | the answer value on Search, the focal point |

Scale ratio 1.2 from 16. Sentence case for every heading and button. At most three text emphasis levels on a screen. No all-caps labels, no labels above headings, no italic emphasis words.

## Space and layout

- **Spacing scale (4-point):** `--space-1` 4, `--space-2` 8, `--space-3` 12, `--space-4` 16, `--space-5` 24, `--space-6` 32, `--space-7` 48, `--space-8` 64. Nothing outside it.
- **Proximity:** 8 inside a group, 24 or 32 between groups.
- **Shell:** a sidebar of 240 px (source list, as in Finder) and the main area. Under 60rem the sidebar becomes a top bar with the same items.
- **Main area:** `max-width: 1200px`, centred, padding 24 (16 on phones). The Viewer is the exception: its page canvas uses the full width.
- **Alignment:** text is left-aligned. Only short empty-state messages are centred.

## Components

- **Radius:** `--radius-control` 6 (buttons, inputs, selected row), `--radius-panel` 10 (panels, dialogs, popovers). Page images have no radius. No pill shapes.
- **Buttons:** primary (filled `--color-primary`, text `--color-on-primary`) and secondary (`--color-raised` with `--color-control-border`). One primary button per screen at most. Labels are verb plus object ("Open page", "File it").
- **Rows:** lists are rows separated by space or a 1 px `--color-border` line, as in Things. There are no cards per row. A selected row gets `--color-primary` at 12% behind it, and the selection is shown by the row's text weight as well as the colour.
- **Panels:** one level of panel. A panel never holds another panel.
- **Status:** shown as an icon plus words, never a coloured badge alone. Doubt: an amber icon and "Not sure:" followed by what was read.
- **Icons:** one SVG set (Lucide), stroke 1.5 px, 16 or 20 px, always with a text label or an `aria-label`.
- **Every control has every state:** default, hover, focus-visible (2 px `--color-focus` ring, 2 px offset), active, disabled, loading, error, empty.
- **Layers:** light mode uses borders for panels and one shadow for floating layers only (`0 8px 24px oklch(0.2 0.02 250 / 0.12)`). Dark mode uses no shadows: a higher layer is a lighter surface.

## Motion

- 150 ms for colour changes on hover and press. 200 ms for a panel or inspector opening, with `transform` and `opacity` only. Never `transition: all`.
- No scroll reveals, no animation library, no looping or pulsing motion.
- `prefers-reduced-motion: reduce` removes movement and keeps the colour changes.
- Waiting for the full reading (about 3.5 s) shows the quick results at once and a text line ("Reading your question"). Nothing pulses.

## Anti-patterns (do not use)

- A dashboard home: stat tiles, charts, KPI cards. The app opens on Search.
- Cards inside cards, a card for every row, badges or pills as decoration.
- Labels above headings, display or italic serif headlines, one coloured word in a heading.
- Cream with terracotta or acid green, gradients, glassmorphism, glow.
- Pulsing or "live" dots, emoji, stock illustrations.
- Web fonts or any asset from a CDN.
- Colour as the only signal of a state.
- An answer without its page and line, or a doubt shown only in colour.

## Before a screen ships

Run the critique checklist in `docs/design-rationale.md` (Accessibility results), at 1440 and 375 px, in light and dark, keyboard only.
