# 0018. The search index lives in SQLite, with exact vectors held in memory
Date: 2026-11-28 · Status: accepted

## Context
Search has to find a document from a few words, by its meaning when the words differ ("fridge" for a refrigerator) and by an exact key when the words are an identifier (an IMEI, a policy number). It has to work on one Mac for a family's papers, which is a few thousand chunks of text, and it must never hold more than the database already holds: no secret, no unmasked card number.

## Decision
**Keywords.** SQLite FTS5, in the app's own database, over each document's stored line text (already masked) and its stored fields. A field is indexed as `<label> <value>`, with dates and amounts written the ways a person types them, so "10 lakh" and "10,00,000" and "29 Jan 2027" all find the field. A prompt's words are quoted one by one before they reach the match, so search syntax is plain words and never an error.

**Vectors.** `qwen3-embedding:0.6b` through Ollama, 1,024 dimensions. A document becomes one summary chunk plus windows of 12 page lines stepping 9, all from stored text and fields. The matrix of vectors sits in memory under a lock and a query is scanned exactly with cosine similarity. About a thousand documents is about 6,000 chunks, which scan in milliseconds, so an approximate index or a SQLite extension would add nothing. The embed jobs run in the same worker as filing, defer when Ollama is off, and are queued again at start-up for any document with no vectors. Undo and refiling update the index in the same transaction as the document, and a vector for a removed document is never returned.

**Fusion.** Reciprocal rank fusion with k = 60 over the rankings that apply: the keyword ranking, the vector ranking, and, when the prompt holds an identifier-shaped word (8 or more digits, or 8 or more characters with 4 or more digits), a third ranking over field rows only. That third ranking is why `invoice IMEI 490154203237518` finds the invoice even though the number sits in one field row and the other words in other rows. Fields that hold an identifier are also indexed by their last four digits, so a prompt where a long number was masked to its last four still finds the document.

**Without the vectors.** When Ollama is off, or the index was made by another embedding model, the keyword ranking falls back to matching any word, ranked by BM25 per document, and the screen says so in one line. With the vectors on, that looser ranking is left out, because fusing it with the vector ranking pulled the right file down.

## Alternatives considered
- **A vector database or an approximate index.** More to install and keep in sync for a vault this small. Exact search is simpler and is exact.
- **Vectors only.** Cannot find an identifier by its characters, and gives an answer even when nothing matches.
- **Keywords only.** Matching all the words inside one line or field found nothing for most natural prompts of two or more words once the vectors were off, which is how the range review found the fallback was broken. The any-word fallback fixed it.
- **A separate search service.** Another process to run and secure on a private Mac, for no gain.

## Consequences
On the test split of `search-v1` (`evals/results/2026-11-28_search_test_93a99db.json`), the quick search, which has no prompt reading, has the right document in its first three rows for 94.7% of lookups and finds, at a median of 0.038 s. With the vectors off, the same measure is 83.3% in the first three and 52.7% first, so the keyword fallback is usable but a clear step down. The leak scan over the index tables found 0 secrets.

Language that is a synonym of a printed word is found only through the vectors, and the keyword index misses it. The embedding model has to be pulled; without it the app says so and still searches by keywords.
