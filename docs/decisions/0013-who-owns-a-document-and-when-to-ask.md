# 0013. Who owns a document, where it goes, and when the app asks instead
Date: 2026-11-20 · Status: accepted

## Context
Filing is the step where a wrong guess does the most harm: a paper in the wrong person's folder stays wrong until someone notices. The requirements say asking is better than guessing, and the target is at most 1 silent misfile per 100 documents. This ADR is the rule set, and the answers I gave when I approved the M2 plan.

## Decision
**Owner.** Each document type has an owner rule, listed by name in `doctypes.py` so a new type without one fails a test. A policy belongs to its policyholder, an ID or card to its holder, a medical paper to its patient, and work, education, tax and vehicle papers to the person named on them. Home policies, property, rent and utility papers belong to `Home` and are linked to the people they name. Every purchase files to `Home/Purchases`, linked to the buyer, so a warranty is in one place whoever paid.

**Folders.** `<Person or Home>/<Area>/<date> <description>.<ext>`, with a subfolder for some medical types (Reports, Scans, Hospital stays, Recordings). The date is the document's own date when the page has one, otherwise the day it arrived, and the record says which.

**Matching a name.** A printed name is matched to the household with aliases, initials and honorifics ignored, at a score of at least 0.8 (`PERSON_MIN`). One clear best match gives the owner. A name that matches nobody is `person_unknown`. Two people tied is `person_unsure`. I did not loosen this match to forgive the model's spelling slips, because a near name could then file under the wrong person without a word. Slips are fixed before matching, from the page's own text (0017).

**Required fields.** Each type lists the fields it cannot be filed without. A missing one is `missing_required`, and one that was read but failed a check (a date that is not a date, a total that does not add up) is `field_issue`.

**One question per document.** Reasons have a fixed order, from `locked` down to `possible_copy`. The app asks about the first one only, and the answer is applied before the rules run again, so the next question, if any, follows. A re-scan of something already filed (same type and key numbers) asks "keep both or discard".

**Two names.** A marriage certificate prints two people. If the reading finds fewer than two names it asks `person_unsure` instead of taking the one name. The first validation run filed one of these silently, and this rule closed it.

**A failed read.** If the model's answer cannot be parsed, the document is held as `read_failed`. Once I name the type, that reason is dropped and the missing-field and person questions follow, so what I type can still file the paper. Before that fix a type answer left the item asking about the read forever.

## Alternatives considered
- **Purchases to the buyer's own folder.** A shared warranty then lives in whoever's folder it landed in. Dropped when I approved the plan.
- **Ask about everything below a confidence score.** The small model's own confidence is not a measure I can check, so the rules ask on things code can test: no matching person, a tie, a required field missing, a check failed.
- **Looser matching to forgive spelling slips.** A near name could file under the wrong person without a word; the spelling snap in 0017 fixes the slip instead.
- **Scoring Needs a look on every document.** Questions that are correct would count against the target. I score it on the documents that need no question by design and publish the raw share beside it.

## Consequences
On the test split of the synthetic set (`evals/results/2026-11-20_reading_test_b2a1fde.json`, the re-measure by replay, see 0017):
- Silent misfiles: 0 per 100 documents.
- Person accuracy: 100.0% (92.4% in the live run, `2026-11-20_reading_test_bcfd85d.json`; every one of those misses was a question asked, none filed wrong).
- Needs a look: 0.0% of the documents that should file without a question, and 13.9% of all documents, since the set holds questions on purpose (outsiders, ambiguous names, missing fields).
- The filing eval's placement matched the decision on 100.0% of documents (`2026-11-20_filing_test_b2a1fde.json`).

Limits: the rules know the names of the household's people and nothing else, so a family with two people of the same name will see `person_unsure` often. A document that names several people sits with its owner and is linked to the rest; there is no "shared" folder besides `Home`.
