# Search screen (overrides MASTER.md where they differ)

**One task:** type a short prompt and get the answer with the page it came from.

- The prompt field is at the top of the main area, full width of the container, `--text-body` at 16 px, focused when the screen opens. Enter runs the full search; results update as you type (the quick search, no model).
- **Focal point:** the answer panel once the full reading returns. The answer value is set in `--text-answer` (28 / 600). Under it comes the "what I understood" sentence, in `--text-caption`, with each part (person, kind of document, which date, when) as a menu. Choosing one runs the lookup again on that change (the API takes the reading the screen holds and the change, with no second model call). Beside it sits a thumbnail of the cited page with the citation box drawn in `--color-cite`. "Open at page" is the one primary button, and it opens the viewer with the answered field marked.
- When the app declines ("No direct answer"), for a lookup or a find alike, the panel says why in one sentence ("No one called Anil is in the household") and shows the closest files as rows. It never shows a guessed value.
- With the embedding model off, one quiet line under the box says "Searching by keyword only: the local model isn't running." (and not a second time beside the reading-off line).
- A part of the prompt the app could not read is an amber "Couldn't read: <words>" line beside the sentence, with an icon. "Not sure:" is kept for a value read from a document that the app doubts (see MASTER, Status).
- Result rows: kind of document, people, then each key field as its own piece (insurer, number), never joined with a dot; the matching words in weight 600, not in colour. Under 60rem the people and the fields wrap instead of clipping.
- The prompt, a typed card number masked to its last four, is the page title; the box is a combobox over the list of rows.
- Keyboard: `/` or Cmd+K focuses the prompt; arrow keys move through rows; Enter opens; Escape clears.
