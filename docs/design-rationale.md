# Design rationale

The tokens are in `design-system/household-docs-vault/MASTER.md`, and the screen rules are in its `pages/` folder. This file says why each choice was made.

## Brief and mood

1. **Who and where:** me, at my Mac, in a browser, keyboard first. Later, the same screens on my phone at arm's length.
2. **One task per screen:**
   - Search: type a short prompt and get the answer with the page it came from.
   - Viewer: check that answer against the highlighted line on the document.
   - Lists: see every matching document and open one.
   - Inbox: answer the one question the filer could not settle, so the file gets filed.
3. **Feel:** calm, precise, private. Calm because these papers are stressful (insurance, IDs, medical reports). Precise because the answers are numbers, dates and names. Private because nothing leaves the Mac.
4. **Never:** show an answer it cannot point to on the page; hide that it was unsure; let a document vanish without a trace. Card numbers and passwords never reach the screen at all, because they stay in the KeePass file. The architecture handles that, not the design.
5. **Looks like** macOS Preview and Finder, and Things 3. **Must not** look like a SaaS dashboard.

What follows from the brief:
- The documents themselves are the visual content, so the interface stays quiet around them. Preview and Finder give me the shell: a sidebar, a grey canvas behind the page, and an inspector beside it. Things 3 gives me the lists: rows with generous type, and no box around each one.
- A dashboard would put stat tiles and charts between me and the one thing I came for, so the app opens on Search.

## Palette

All colours are in OKLCH. Its lightness channel matches what the eye sees, so steps that look even are even, and I can predict contrast from the lightness difference.

- **Brand, blue (hue 255):** blue reads as calm and trustworthy, and it is the colour macOS already uses for selection and focus. A Mac user's eye already knows what it means. I use it for the primary button, links, the focus ring, the selected row and the citation box. Light `oklch(0.52 0.15 255)`; dark `oklch(0.72 0.11 255)`, lighter and less saturated, because saturated colours vibrate on dark backgrounds.
- **Neutrals:** about 95% of the pixels are background, text and lines, so the neutrals matter more than the brand. They carry a faint tint of the brand hue (chroma 0.004 to 0.015), so the page feels like one family instead of a grey frame around a blue button. In dark mode, higher layers get lighter surfaces instead of shadows, because shadows barely show on dark.
- **Accent:** none beyond the brand blue. A second accent would compete with the one action on each screen.
- **Doubt, amber (hue 65 to 75):** amber is the "warning" colour, and here it means one thing only: the app is not sure. That serves the rule "never hide that it was unsure". It is never the only signal: a doubt always has an icon and the words "Not sure:" followed by what was read.
- **Danger, red (hue 25), and success, green (hue 150):** kept at the same lightness and chroma as the brand, so they sit in the same family. Each is paired with words, because about 1 in 12 men cannot tell red from green.
- **Info:** the brand blue, so there is no extra colour.
- **Citation, deep blue in both modes:** the citation box is drawn on the page image, and a scanned page stays white even in dark mode. The dark-mode blue measured 2.18:1 on white paper, too faint to see. The light-mode blue measures 5.25:1, so the citation uses it in both modes.

## Type

- **System sans** (SF Pro on the Mac) for everything. It is what Preview, Finder and Things use, so the app feels native.
- **No web fonts.** A font CDN would add a network request from a private, offline app.
- **System mono** for identifiers only: policy, account, ID and serial numbers. These get read character by character and compared, and a mono face keeps 0 and O, 1 and l apart.
- **Tabular figures** on every date and amount, so columns of numbers line up like a bank statement.
- **Scale and sizes:** ratio 1.2 from a 16 px base: 13, 16, 19, 23 and 28. 16 px body is the smallest that reads without zoom on a phone. The answer value at 28 px is the largest thing on Search, because it is what I came for.
- **Line height and weights:** 1.5 for body and 1.2 to 1.3 for headings, with two weights (400 and 600). Hierarchy comes from size and weight, not colour.

## Spacing and layout

- **Spacing:** a 4-point scale (4, 8, 12, 16, 24, 32, 48, 64) and nothing outside it. Space inside a group is 8; space between groups is 24 or 32. Space then does the grouping, so I don't need boxes.
- **Shell:** a 240 px sidebar as in Finder, which becomes a top bar under 768 px. The main area is capped at 1200 px and centred, so lines don't stretch on a wide screen.
- **Viewer:** uses the full width, because the page image is the content.
- **Text:** left-aligned for easy scanning. Only a short empty-state message is centred.

## Components

- **Radius:** 6 for controls and 10 for panels, both close to macOS. No pills: a pill shape says "badge", and the app has no decorative badges.
- **Buttons:** one primary button per screen at most, so the next step is never in doubt. Labels say verb plus object ("Open page", "File it").
- **Sidebar:** it holds Search, Inbox and my twelve areas as one-click lists, as Finder's source list does. That way browsing an area needs no typing and no model, and it still works when a prompt is misread. The waiting count sits beside Inbox as plain text ("Inbox 3"), never a badge. Under 60rem it folds into a top bar with a Menu button.
- **Lists:** rows, not cards. A card per row is a box doing the job that space can do. Panels are one level deep and never nested.
- **Status:** always an icon plus words. The Inbox count is plain text beside its name, not a red dot.
- **States:** every control has all of them (default, hover, focus-visible, active, disabled, loading, error, empty), because a control that only has a hover state feels broken the first time it is used from the keyboard.

## Motion

- **What moves:** only feedback. Colour changes take 150 ms and a panel opening takes 200 ms, using `transform` and `opacity` only.
- **What doesn't:** no scroll reveals, no animation library and nothing that pulses. A pulsing dot fakes a "live" signal.
- **Waiting:** a full search waits about 3.5 s for the prompt reading. The quick results show at once, and one line of text says it is reading the question.
- **Reduced motion:** with it on, movement is removed and colour changes stay.

## Accessibility results

**Contrast pairs.** WCAG 2.x ratios, computed from the OKLCH values. Targets: 4.5:1 for text, 3:1 for borders and focus.

| Pair | Light | Dark |
|---|---|---|
| Text on background | 16.57 | 15.03 |
| Text on raised panel | 17.06 | 13.20 |
| Muted text on background | 6.53 | 7.45 |
| Muted text on sidebar | 6.16 | 7.07 |
| Muted text on raised panel | 6.72 | 6.54 |
| Text on the primary button | 5.41 | 7.45 |
| Primary (links) on background | 5.33 | 7.45 |
| Focus ring on background | 4.14 | 8.01 |
| Focus ring on sidebar | 3.91 | 7.59 |
| Control border on raised panel | 3.59 | 3.35 |
| Control border on background | 3.48 | 3.81 |
| Doubt text on its background | 5.42 | 7.26 |
| Doubt text on background | 5.92 | 9.77 |
| Danger on background | 5.76 | 7.30 |
| Success on background | 5.46 | 8.98 |
| Citation box on white paper | 5.25 | 5.25 |

Every pair passes. The dark-mode control border failed at first (2.95:1 on a raised panel), and I fixed it by raising its lightness from 0.52 to 0.55, keeping the hue.

**Keyboard, focus and tap targets** are checked when the screens exist (Tasks 33 to 36). The method: desktop at 1440 px and phone at 375 px, light and dark, with only the keyboard; then an automated checker, and a hand fix of whatever it misses. The results go here.

## Tried and rejected

- **A first generated draft:**
  - a landing-page layout (product demo, call to action) for what is an app, not a marketing page;
  - teal with an orange accent on a mint background;
  - a font described as friendly and SaaS-like;
  - scroll-reveal animations.

  Each one pulled toward the dashboard look the brief rules out, so I dropped them all.
- **A second draft:** a blue with an amber accent. I kept the blue and moved amber to one meaning only, doubt. As a general accent, it would have made every "not sure" note look like decoration.
- **Inter from a font CDN:** dropped for the system font. Same reason as above: no network requests from a private, offline app.
