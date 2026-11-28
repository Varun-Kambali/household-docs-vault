# 0021. The search-v1 eval set, tuned on validation and scored once on test
Date: 2026-11-28 · Status: accepted

## Context
Search has to be measured on documents and questions it was not tuned on, with an answer key that does not depend on the app. [ADR 0016](0016-synthetic-eval-set-v1.md) did this for reading; search needs a vault to search in and questions to ask it.

## Decision
**The vault of a split.** It holds the split's `eval-v1` documents in the photo variant, filed by the real worker from their recorded readings, plus the same split of two more synthetic sets, `search-x1` and `search-x2` (seeds 11 and 12), filed from oracle readings. The extra sets use `eval-v1`'s per-type counts with outsider, unclear-name and missing-field rates set to 0, so each one files. The result is a vault about three times the size of the `eval-v1` split. Questions about `eval-v1` documents measure reading and search together, and questions about the extra ones measure search alone, so the results report the two origins apart. A document whose truth is a question (an outsider, unclear initials, a missing required field) is in the vault and counted as left out, and no question targets it, because it is never filed.

**The questions.** 210 a split: 100 lookups (one stored value of one document), 50 finds (name a document), 40 lists (people, areas, types, a date field, a place and a date phrase) and 20 with no answer (a type, a product or a person the vault does not hold). In styles: full questions, terse prompts, one-letter typos and synonyms ("fridge", "mediclaim"). On the test split (`evals/datasets/search-v1/summary.json`): 177 documents, 169 of them filed (51 eval-v1, 118 extra), 94 full questions, 60 terse, 40 typos and 16 synonyms; 67 questions about eval-v1 documents and 143 about the extra ones.

**The answer key** is built from the generator's truth, not from the app. A target is every filed document that fits the words of the prompt, and the generator drops a question when its targets do not share one value. A list's expected set comes from applying the structured query to the truth fields. "Today" is fixed at 20 Nov 2026 so a date phrase has one meaning.

**Tuning and the test run.** The reading prompt, its vocabulary words, the weak-match thresholds, the fusion settings and the chunk sizes were tuned on the validation split only, by replaying recorded readings and vectors with no model call, and then by live runs. The test split was run once, live, on commit 93a99db, and nothing was changed after it. Prompts and recordings for that run are committed in `evals/recordings/search-v1/test/`.

**Five prompts appear in both splits.** Five test prompts are word for word the same as validation prompts, so their readings were tuned on: `test-lookup-048`, `test-lookup-049`, `test-lookup-062`, `test-list-005` and `test-list-025`. The results file reports them apart (`seen_in_val`: all five were answered right, and none was declined), and every rate in the run still clears its target without them.

**How "declined" is scored.** A question is declined when the route returns a no-answer outcome, or no row at all. The eval reads what the route returns, not its own rule, so the screen and the score cannot drift apart. The first version of the eval counted a find that named an unknown person as declined while the screen showed other members' files, and the range review caught that.

## Alternatives considered
- **Real documents.** Not in a public repo, and not sent to a model.
- **Questions written by hand.** Too few, and they would carry my own wording. Templates are visible and checkable.
- **One split.** Tuning on the set I report would flatter every number.

## Consequences
Every search number in the README and the case study comes from `evals/results/2026-11-28_search_test_93a99db.json`. The documents are synthetic and the questions are template-made, so the numbers say how the app behaves on this kind of paper and prompt, not how it will do on mine. The check on my own documents at the end of the project is the real one.
