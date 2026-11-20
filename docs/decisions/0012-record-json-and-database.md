# 0012. One record file per document, and a database on the Mac that the records can rebuild
Date: 2026-11-20 · Status: accepted

## Context
0006 put the database on the Mac's disk and said it could be rebuilt from a record JSON per document, with the format left for the milestone that wrote the filer. M2 wrote it. Two things pulled against each other: the record has to hold enough to recreate the database rows, and it sits in the Drive-synced folder next to the documents, so it must never hold a secret or an identifier I would not put in a file name.

## Decision
Filing writes `_system/records/<id>.json` for every filed document, in this order: copy the file, verify the copy's SHA-256, write the record, update the database, clear `Inbox`. The record has `record_version: 1` and holds the document id, the item id, the type, the owner and linked people (the owner is never in the linked list), the area, the path, the SHA-256, the document date and whether it came from the page or from the day I received it, the description, the fields and the issues, the pages with every line's text and box, and the engine, prompt version and seconds of the reading.

Four rules keep it safe to sit in Drive:
- Secret fields are `null`. A card's number and CVV go to `Secrets.kdbx` and the record keeps only `secret_ref` (0014).
- Line text is stored after card numbers are masked, and on card pages and pages of unknown type every run of three or more digits is masked as well.
- `original_name` is the file's name with anything shaped like an identifier removed, and `origin` says `inbox` or `upload`. A rebuild can then recreate the item row, including the fact that an uploaded card never sat in Drive.
- Floats are rounded (boxes to 4 places, confidence to 3, seconds to 1), so the leak scan does not read a long fraction as a number.

The database is SQLite at a path outside the vault (`VAULT_DB` in development, the app's own folder when installed). `record_rows` turns one record into the document row, the owner and linked rows and the page text, and the crash tests use it to check that a filing stopped half-way ends with the same rows as one that was not.

## Alternatives considered
- **Records only, no database.** Search, reminders and the Needs a look list would scan every file. 0006 already ruled this out.
- **A record per document that also holds the secrets**, so the database and KeePass could both be rebuilt. It would put a card number in a plain file in Drive, which is the thing 0004 exists to prevent.
- **Unmasked line text in the record**, masking only on the way into the database. A record that is safe only if nobody reads it is not safe.
- **A version field only when the format first changes.** Adding it now costs one line and means a later reader can tell old records from new.

## Consequences
- The command that rebuilds a whole database from the records is not written yet; M2 built and tested the record and the row conversion it needs.
- Records are scored by the same leak scan as everything else the app writes. The test run found none (0 secrets, `evals/results/2026-11-20_filing_test_b2a1fde.json`).
- Masked line text is what a rebuild gets back. Card pages and pages of unknown type lose digit runs for good, which does not matter because card pages are never searched by content (3).
- Any change to the record's shape means `record_version: 2` and a reader for both.
