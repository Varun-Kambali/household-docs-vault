# 0017. Values are read as printed and converted by code, and spelling slips are fixed from the page's own text
Date: 2026-11-20 · Status: accepted

## Context
The first validation run on the synthetic set, with the M1 prompt carried over as prompt v2, got 86.5% of fields on photos exactly right against a target of 92%. The misses were not random. In that run, 38 of 72 field misses on correctly typed documents were the vision model converting a format the app already parses: day and month swapped in a date, `Rs. 10,00,000` returned as 10000 or 10000000. Another 24 were spelling slips. Two silent misfiles came from a marriage certificate read with one name, which 0013 now stops.

## Decision
**Read as printed.** From prompt v3 the fill prompt tells the model to copy dates, amounts and names exactly as printed, with separators and in the page's own order, and never to correct, complete or shorten a name. The app's own day-first date parser and Indian amount parser (`10,00,000`, `Rs.`, lakh and crore) convert them. Schema descriptions say the same for fields where the hint would otherwise be missing, such as seller location, the two parties of a marriage certificate and a medicine's dose and timing. Prompt v4 changes only the type guide (0015). Older prompts are frozen under their names.

**The spelling snap.** After the fill, a name, text or address field whose value is not on the page, but is a near match to the page's own OCR text, takes the OCR spelling. It only fires when the match ratio is at least 0.85, edits stay within the larger of 2 or 15% of the length, the best candidate beats the next by a margin, and the field still validates afterwards. Identifiers, dates, amounts and secret fields are never touched. It runs on the unmasked English lines, after secret fields are taken out and before card masking. I use it because the vision model misspells a name (`SURESH N RAO` as `SURESHER`) that Apple Vision read right (98.7% line recall on photos).

**One re-measure, by replay.** The snap was built after the test run, because the test misses were all of this kind. It was validated on `val` by replay, then the committed test recordings were replayed through the new code once (`2026-11-20_reading_test_b2a1fde.json`), with no model call. It is the only change made after the test run, and `evals/results/summary.md` says the numbers are a replay.

## Alternatives considered
- **Prompt v2, asking for ISO dates and plain numbers.** Dropped: it produced the 38 misses above.
- **Fuzzy matching a printed name to the household's aliases.** A near name could file under the wrong person without a word. The snap changes the spelling of the field before matching and leaves the matching strict.
- **Accept the misses and revisit in M6.** All 11 owner misses on test were questions asked, none filed wrong, so it was a real option. I chose to fix it because Apple Vision already had the right spelling on the page.
- **A larger model.** 0009 measured the 8 billion one: one more field right out of 120, at nearly twice the seconds.

## Consequences
On the validation split (not committed): the prompt rules took fields on photos from 86.5% to 96.7% and the type guide to 97.6%; the snap took them to 99.4%, person accuracy from 97.9% to 100%, with 22 fields wrong to right and none right to wrong.

On the test split, the live run before the snap against the replay after it:

| Measure | Live run (`bcfd85d`) | Replay with the snap (`b2a1fde`) |
|---|---|---|
| Fields exactly right on photos | 96.7% | 99.7% |
| Fields exactly right, all documents | 96.1% | 99.4% |
| Person accuracy | 92.4% | 100.0% |
| Linked people accuracy | 93.6% | 100.0% |
| Field F1 | 93.3% | 96.6% |
| Needs a look, documents that should file | 6.8% | 0.0% |
| Silent misfiles per 100 | 0.00 | 0.00 |

Source: `evals/results/2026-11-20_reading_test_bcfd85d.json` and `..._b2a1fde.json`.

The replay is not a clean measurement of the shipped reader. The committed recordings hold long digit runs masked, so a field made of one, such as the acknowledgement number on an ITR acknowledgement, scores wrong on replay even though the live read was right (three documents, which is why that type is the lowest at 75%). Seconds come from the live run, since a replay takes none. Where a replay number and a live number differ, the README shows the replay and says so, and this table has both.

The snap can only help when the page's OCR has the right spelling. Where Apple Vision misreads a name too, the model's slip stays and the owner is asked.
