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
- **Citation, deep blue in both modes:** the citation box is drawn on the page image, and a scanned page stays white even in dark mode. The dark-mode blue measured 2.48:1 on white paper, too faint to see. The light-mode blue measures 5.56:1 on pure white and 5.25:1 on a paper tone at lightness 0.98, so the citation uses it in both modes. On a grey paper (lightness 0.93) it is 4.53:1, still readable as a box outline, which needs only 3:1.

## Type

- **System sans** (SF Pro on the Mac) for everything. It is what Preview, Finder and Things use, so the app feels native.
- **No web fonts.** A font CDN would add a network request from a private, offline app.
- **System mono** for identifiers only: policy, account, ID and serial numbers. These get read character by character and compared, and a mono face keeps 0 and O, 1 and l apart.
- **Tabular figures** on every date and amount, so columns of numbers line up like a bank statement.
- **Scale and sizes:** ratio 1.2 from a 16 px base: 13, 16, 19, 23 and 28. 16 px body is the smallest that reads without zoom on a phone. The answer value at 28 px is the largest thing on Search, because it is what I came for.
- **Line height and weights:** 1.5 for body and 1.2 to 1.3 for headings, with two weights (400 and 600). Hierarchy comes from size and weight, not colour.

## Spacing and layout

- **Spacing:** a 4-point scale (4, 8, 12, 16, 24, 32, 48, 64) and nothing outside it. Space inside a group is 8; space between groups is 24 or 32. Space then does the grouping, so I don't need boxes.
- **Shell:** a 240 px sidebar as in Finder, which becomes a top bar under 60rem (960 px, the same breakpoint the code uses). The main area is capped at 1200 px and centred, so lines don't stretch on a wide screen.
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
- **Waiting:** a full search takes a median of 3.24 s and 3.84 s at the 95th percentile (`evals/results/2026-11-28_search_test_93a99db.json`, the reading call is most of it). The quick results show at once, and one line of text says it is reading the question.
- **Reduced motion:** with it on, movement is removed and colour changes stay.

## Accessibility results

Checked on the built app, on the synthetic vault, at 1440 px and 375 px, in light and dark, with the keyboard only; the same screens run through an automated accessibility checker in CI (pa11y), which has 0 errors on every screen, and a hand fix for what it cannot see. The pairs below were computed exactly from the OKLCH values after the audit at the end of M3, and the on-screen readings were within 0.06 of them.

**Contrast pairs.** WCAG 2.x ratios. Targets: 4.5:1 for text, 3:1 for borders, focus rings and non-text signals.

| Pair | Light | Dark |
|---|---|---|
| Text on background | 16.57 | 15.03 |
| Text on sidebar (navigation links) | 15.64 | 14.26 |
| Text on raised panel (panels, dialogs, buttons) | 17.06 | 13.20 |
| Muted text on background | 6.53 | 7.45 |
| Muted text on sidebar | 6.16 | 7.07 |
| Muted text on raised panel | 6.72 | 6.54 |
| Text on the primary button | 5.41 | 7.45 |
| Text on the primary button, hovered and pressed (approximate, the mix is in sRGB) | 6.25 and 7.06 | 8.15 and 8.77 |
| Text on a hovered or pressed secondary button | 15.14 and 13.94 | 11.31 and 10.09 |
| Primary (links) on background | 5.33 | 7.45 |
| Primary (links) on raised panel (the skip link) | 5.49 | 6.54 |
| Text on the selected sidebar row | 13.30 | 11.69 |
| Text on the hovered sidebar row | 13.90 | 12.36 |
| Text on a selected choice or size option | 14.43 | 10.72 |
| Text on the selected result row | 14.05 | 12.47 |
| Muted text on the selected result row | 5.53 | 6.18 |
| Text on a hovered result row | 14.72 | 13.19 |
| Muted text on a hovered result row | 5.80 | 6.54 |
| Focus ring on background | 4.14 | 8.01 |
| Focus ring on sidebar | 3.91 | 7.59 |
| Focus ring on raised panel (dialogs, inspector) | 4.26 | 7.03 |
| Focus ring on the grey canvas (viewer, Inbox page) | 3.52 | 8.48 |
| Control border on raised panel | 3.59 | 3.35 |
| Control border on background | 3.48 | 3.81 |
| Doubt text on its own background | 5.42 | 7.26 |
| Doubt text on background | 5.92 | 9.77 |
| Danger text on background | 5.76 | 7.30 |
| Danger on raised panel (the danger button) | 5.93 | 6.42 |
| Success on background | 5.46 | 8.98 |
| Success on raised panel (the filed notice icon, non-text) | 5.62 | 7.88 |
| Citation box on white paper | 5.56 | 5.56 |
| Citation box on paper at lightness 0.98 | 5.25 | 5.25 |
| Citation box on grey paper at lightness 0.93 | 4.53 | 4.53 |
| Dark-mode brand blue on white paper (why the citation colour is fixed) | not used | 2.48 |

Every text pair is 4.5:1 or better in both themes. The lowest required pair is the focus ring on the grey canvas at 3.52:1 in light mode, over the 3:1 bar. The dark-mode control border failed at first (2.95:1 on a raised panel), and I fixed it by raising its lightness from 0.52 to 0.55, keeping the hue. Two things are exempt or decorative and are not in the table: a disabled primary button (the disabled state is exempt from the text rule) and the hairline border between regions (1.33:1 in light mode), which only separates and carries no meaning.

**Keyboard and focus.**
- The search box has focus when the app loads. Tab then goes sidebar first, then the main area, and on the search screen the order inside it is the prompt, the answer's buttons, the citation box, then the skip link and the sidebar.
- On a route change, the page's heading takes focus with no outline, so a screen reader starts at the top of the new page.
- Every control shows a 2 px ring in the focus colour with a 2 px offset; the citation box in the viewer has a thicker one.
- Arrow keys move through the quick finder's rows, Enter opens the active row or runs the full search, and Command and Enter shows the file in its folder. On the answer, the cited line is a button, and Enter on it opens the viewer on that page with the line outlined and scrolled into view.
- Opening an area from the sidebar with Enter lists it with no model call, and changing a part of a list's sentence is a select that can be used from the keyboard.
- The phone menu opens with Enter (`aria-expanded` turns true), Escape closes it and puts focus back on the Menu button.
- The Inbox: key 1 and Enter answer a question with its first choice, focus then moves to the next question's heading, and the empty Inbox sentence takes focus. The password and secrets dialogs put focus in the labelled field, and after the dialog closes no password is left in a field, the address, local storage or session storage.
- The search box follows the ARIA combobox pattern (role, `aria-expanded`, `aria-autocomplete`, `aria-controls` and `aria-activedescendant`), so a screen reader announces the active row. The range review found it missing and the fix wave added it.

**Tap targets.** Buttons and sidebar links have a 44 px hit area (a `::before` area on the control). Text inputs and selects are 40 px high, because a native select cannot extend its hit area; 40 px is above WCAG's 24 px minimum for targets, and I accepted it. After the fix wave, the Inbox file button is 44 px on phones too.

**No sideways scroll** at 375 px on any screen, and the inspector sits below the page on a phone.

**Critique checklist** (the cookbook's section 12), on each screen, after the fixes from the audit at the end of M3. The audit found five failures; each is closed:

| # | Question | Result |
|---|---|---|
| 1, 2 | Job clear in 5 seconds, and exactly one focal point | Yes on every screen. At 375 px the Inbox put the image before its question; a CSS order change under 60rem puts the question first |
| 3 | Squint test | Yes. The Inbox's activity log adds noise, and its rows are quieter after the fix |
| 4 | Contrast in both themes | Yes, every pair in the table above |
| 5 | Focus visible on every control | Yes |
| 6 | All control states | Yes. Rows, selects and file inputs were missing hover, pressed and disabled states and now have them; a disabled button now gives its reason |
| 7, 8, 9 | Spacing, sizes and at most two font families, all from the tokens | Yes (system sans and system mono) |
| 10 | Colour never the only signal | Yes. Doubt is an icon and words, status is an icon and words |
| 11 | Reduced motion, and content without JavaScript | Yes for motion. Without JavaScript the app shows a notice, which is right for a local app and is a recorded decision |
| 12 | Phone width, no sideways scroll | Yes |
| 13 | All content real | Yes (synthetic vault data) |
| 14 | AI tells absent | Yes after the fix. List rows had fields joined by middle dots and the Inbox had three equal buttons on every row; rows now wrap their fields and the row actions are quiet until needed |
| 15 | Rationale written down | Yes, this file |

## Tried and rejected

- **A first generated draft:**
  - a landing-page layout (product demo, call to action) for what is an app, not a marketing page;
  - teal with an orange accent on a mint background;
  - a font described as friendly and SaaS-like;
  - scroll-reveal animations.

  Each one pulled toward the dashboard look the brief rules out, so I dropped them all.
- **A second draft:** a blue with an amber accent. I kept the blue and moved amber to one meaning only, doubt. As a general accent, it would have made every "not sure" note look like decoration.
- **Inter from a font CDN:** dropped for the system font. Same reason as above: no network requests from a private, offline app.
