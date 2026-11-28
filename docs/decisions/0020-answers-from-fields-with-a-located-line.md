# 0020. An answer comes from stored fields and a located line, or the app says there is none
Date: 2026-11-28 · Status: accepted

## Context
The project fails if it shows an answer it cannot point to ([requirements](../requirements.md), anti-goals), and a wrong answer about someone else's document is worse than no answer. A language model that writes the answer sentence can drift from the page, so I wanted the answer to be something I can check on the page in one glance.

## Decision
**Code writes the answer.** No model writes a sentence, a date or a number. `compose` takes the best row that passes the query's person and type filters and builds the answer from that document's stored fields: "Policy number P/21/...", "Yes, until 29 Jan 2027" for a validity question, "Compressor: yes, until 13 Mar 2034. Comprehensive: ended 13 Mar 2025" for a warranty. A warranty part's last covered day is the purchase date plus its years, less one day, which is how a policy states its end.

**A located line, or no direct answer.** A value is shown only when a line on the page prints it. `locate` looks for the date, amount, identifier or words in the stored lines of the page, and the answer carries the page and the line boxes it found. A value with no line printing it is declined. When it declines, the app says "No direct answer" with a plain reason and shows the closest files.

**The weak-match rule.** A top row with no filter behind it is declined when its fused score is under 0.02 and fewer than one of its lines matched the words. A query with leftover words, such as a product or a brand, is declined when no row matches them by keyword or by a vector score of 0.62 or more. Both numbers were tuned on the validation split only.

**Who it is about.**
- A lookup or a find that names someone outside the household is declined with the reason `unknown_person`. It is never answered from another member's document.
- A find with no document that fits the person and the type asked is declined with `no_documents` and shows the closest files, because a finder that quietly lists other people's files looks like an answer.
- A list that names an unknown person is shown with the part it could not read, in doubt colour, and the list is what the rest of the prompt gives.
- An outsider's name is recognised when it is written as a possessive ("Meera's PAN card") and is not a household name, a word of a stored place, shop, brand, product or insurer, a type or a field word. "Samsung's invoice" and "Care's health policy" are therefore not read as people.

**Hard and soft filters.** People and types are hard filters. Place, area and date range are soft: they rank and shape a list, but they do not stop a lookup from answering. The reason is that a typo in a place ("hospotal") would otherwise decline an answerable question. The trade-off is real: "the order ID on the Vijay Sales invoice", when the vault holds no Vijay Sales invoice, can be answered from another shop's invoice. That case is recorded for search-v2, and the question set does not test it yet (it was frozen before the test run).

## Alternatives considered
- **A model writes the answer from the page.** More fluent, and I could not check it against the page without reading the page myself.
- **Always show the top row.** Never declines, so the eval's "answerable declined" rate would be 0 and the wrong-answer rate would be high.
- **Treat every filter as hard.** Declines typos, and the shape of a shop name differs from how a person says it.
- **Catch a bare outsider name with no possessive** ("Anil life insurance policy"). I tried a rule that treats any unknown capitalised word at the start of a prompt as a person. On the validation questions it caught one more none prompt and made the app decline many answerable ones, so I dropped it. A bare outsider name is a known limit.

## Consequences
On the test split of `search-v1` (`evals/results/2026-11-28_search_test_93a99db.json`): 90.0% of 100 lookups are answered correctly (83.9% of the 31 about eval-v1 documents, 92.8% of the 69 about the extra ones); every one of the 91 answers given cites the right page and a line that overlaps the true one (citation accuracy 100.0%); 85.0% of the 20 questions with no answer are declined; and 8.7% of the 150 answerable lookups and finds are declined. The causes of the misses are listed in the file (`causes`): retrieval, a misread prompt, an unknown person, a wrong value and three none prompts that were not declined.

Limits I know about:
- **The typing window.** A card number typed into the box is masked to its last four once it is a complete card-shaped run. While it is being typed, the digits so far reach the address bar and the quick search, and so the local embedding model. The server masks again before the reading and embedding models see a finished prompt. Nothing is stored, and the prompt is never logged, but the window exists.
- **Bare outsider names** are not caught (above).
- **The soft place filter** (above).
- **Card numbers masked by shape** also mask a card-shaped policy number in a prompt. An IMEI, or any 10 to 13 digit run, stays whole.
