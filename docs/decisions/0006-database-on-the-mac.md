# 0006. The database stays on the Mac
Date: 2026-11-11 · Status: accepted

## Context
The app needs a database for people, documents, pages, line boxes, fields, reminders and the job queue, and it needs full-text and vector search. The files live in a Drive-synced folder (ADR 0002). Sync tools copy files while they are being written, and a live SQLite file copied mid-write can be corrupted or turned into a conflict copy.

## Decision
The database is SQLite on the Mac's local disk, outside the Drive folder. It holds everything the app needs, including the full-text and vector indexes. It is rebuildable: every document has a record JSON in `_system/records/` in the vault, with type, person, fields and page boxes, so the database can be recreated from the files and the records. A nightly copy goes to `_system/backup/`. How the copy is taken is decided in the milestone that builds it.

## Alternatives considered
- **The database inside the Drive folder.** Risk of corruption by sync.
- **Records only, no database.** Search, filters and reminders over many JSON files would be slow and awkward to write.
- **A separate database server.** More to install and keep running for one user.

## Consequences
The record JSON format becomes part of the design; its details are settled in the milestone that builds it. A rebuild takes time proportional to the vault. Losing the Mac loses nothing that cannot be rebuilt, apart from settings in the local config.
