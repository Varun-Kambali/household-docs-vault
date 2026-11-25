# Search screen (overrides MASTER.md where they differ)

**One task:** type a short prompt and get the answer with the page it came from.

- The prompt field is at the top of the main area, full width of the container, `--text-body` at 16 px, focused when the screen opens. Enter runs the full search; results update as you type (the quick search, no model).
- **Focal point:** the answer panel once the full reading returns. The answer value is set in `--text-answer` (28 / 600). Under it comes the "what I understood" sentence, in `--text-caption`, with each part (person, type, date, place) as a quiet button that opens its choices. Beside it sits a thumbnail of the cited page with the citation box drawn in `--color-cite`. "Open page" is the one primary button.
- When the app declines ("No direct answer"), the panel says why in one sentence ("No one called Anil is in the household") and shows the closest files as rows. It never shows a guessed value.
- Doubt is an amber "Not sure:" line inside the answer panel, with an icon and the words read.
- Result rows: title, person, date (tabular), place, in one line; the matching words in `--text` weight 600, not in colour.
- Keyboard: `/` or Cmd+K focuses the prompt; arrow keys move through rows; Enter opens; Escape clears.
