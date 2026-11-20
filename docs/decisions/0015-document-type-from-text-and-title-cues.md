# 0015. The document type comes from the page's text, and title cues only check the model
Date: 2026-11-20 · Status: accepted

## Context
The type decides the schema, the folder, the owner rule and the questions, so a wrong type is the most expensive reading mistake. 0009 chose a vision model to fill the fields. The type is a different job: a small label from a list of 50 types plus `other`, which the page's title usually settles. M2 had to pick what reads the page for it and what happens when it is unsure.

## Decision
**The type call reads text, not the image.** After Apple Vision reads the page (0008), a separate call to the local model gets the list of types and up to 6,000 characters of the page's text, top to bottom, and answers with one type or `other`. The text is masked first (every 13 to 19 digit run), so a card number never goes into this prompt. The call is retried once if the answer is not valid JSON or names an unknown type, and then counts as `other`. The fill then runs on the page image with that type's schema.

**A type guide.** The first validation run confused a handful of types, so the prompt carries a short guide for them, one line each: a tax proof against an investment declaration, a scan photo against a radiologist's report, a card welcome letter against a card, a prescription against a hospital bill. The first version (v3) typed a lab report from "Prima Scan and Labs" as a scan report, because the centre's name says Scan. Version v4 adds a lab report line ("test results with units and reference ranges, even when the lab's name says Scan") and tightens the scan report line. Older versions are frozen under their names, because recordings and results name them.

**Title cues check the model; they never decide.** Each type has a few lowercase phrases from its title ("personal accident insurance schedule", "fastag issuance details"). After the model answers, the cue check says `agrees` (the model's type has the longest matching cue), `silent` (no specific cue on the page) or `conflicts` (another type has a longer cue). A conflict sends the document to `Needs a look` as `type_unsure`. A generic phrase such as "policy schedule" is on pages of several types, so it can never make a check conflict.

**`other` is never an answer I can give.** A document the model calls `other` is held as `type_unsure` under the label "Unsorted document", but `other` is left out of the options the app offers, because answering with it set the type, which asked again, forever. A document with no English text is held as `no_english`.

## Alternatives considered
- **Let a matching cue decide the type when the model says `other`.** Cues are phrases from my synthetic forms and from common wording, not a classifier. If they could decide, a page that merely mentions "income tax department" would be filed as a PAN card. Rejected.
- **Type from the page image in the same call as the fields.** One model call fewer, but the type then rides on the slowest, least predictable step, and a wrong type would also mean the wrong schema in the same pass.
- **A rules-only classifier on cues.** Fast, and it works on the synthetic titles, which is why I did not trust it to score itself.

## Consequences
On the validation split the first run typed 93.0% right. The v3 prompt with its guide took that to 98.4%, the lab report line in v4 to 100%; a type-only pass of the v4 guide over all 187 validation texts gave 187 of 187, against 184 recorded. I fixed nothing on the test split. Test run, once, with prompt v4: **type accuracy 100.0%** in both the live run and the re-measure (`evals/results/2026-11-20_reading_test_bcfd85d.json`, `..._b2a1fde.json`).

Limits: the cues and the guide were written with the synthetic set in view, so 100% on synthetic pages says little about a real insurer's cover page that opens with a logo and a legal notice. The guide is a prompt for a 4-billion-parameter model, and the next document it confuses will need another line. `other` documents wait for me.
