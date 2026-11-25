# Viewer screen (overrides MASTER.md where they differ)

**One task:** check an answer against the highlighted line on the document itself.

- Like Preview: the page image is centred on `--color-canvas`, using the full width of the main area. Pages stack vertically. There is no radius and no shadow on the page; a 1 px `--color-border` edge only.
- **Focal point:** the cited line. A box in `--color-cite`, 2 px, with `--color-cite-fill` inside. On open the page scrolls the box into view, with no animation under reduced motion.
- A right inspector panel (320 px, `--color-raised`) lists the stored fields as label and value rows. Values use tabular figures; identifiers use the mono stack. The field the answer came from is marked with the selected-row style, and choosing a field moves the citation box to its line.
- Doubt on a field: the amber "Not sure:" line under that field's value.
- "Show in folder" is a secondary button in the inspector.
- Keyboard: arrow keys or J and K move between pages; Tab moves through the fields; Escape returns to the results.
- Under 768 px the inspector moves below the page.
