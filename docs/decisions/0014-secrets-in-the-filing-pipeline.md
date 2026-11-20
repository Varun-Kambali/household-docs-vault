# 0014. How secrets are kept out of everything the filing pipeline writes
Date: 2026-11-20 · Status: accepted

## Context
0004 chose a KeePass file for card numbers, CVVs, PINs and passwords. M2 had to make that true in a pipeline where a vision model reads a card photo, the filer writes records and copies, a database holds lines of page text, and an API serves files. The first plan guarded the places where the model should put a secret. The range review at the end of M2 showed that was the wrong shape: a card number the model wrote into a field it should not have, such as `last4` on a card letter or `card_name`, was stored and served whole. Fixing it took four rounds, and each of the first three found another route to the raw photo. After the third I stopped patching routes and put the protection behind one gate.

## Decision
**Unlock.** The master password opens `Secrets.kdbx` for 10 minutes, in memory only, never in a file, the database or a log. A card photo that arrives through Drive's `Inbox` while the store is locked waits as `waiting_secrets`, and is read and filed in the background once I unlock.

**Masked copy, re-read.** The filed copy of a card photo has the number line blacked out (tilts up to 15 degrees are covered). The app reads that copy again with Apple Vision before filing, and refuses to file it if three digits in a row from the number can still be read. The original goes into the KeePass entry as a protected attachment, and Undo writes it back from there.

**What a waiting original means.** A card photo sitting in the Drive `Inbox` while a question about it waits is not counted as a leak. The app never wrote that file, Drive already holds it from the moment I dropped it, and moving it sooner protects little. The leak check skips only a file directly in `Inbox` that is that item's own path and still hashes to what was recorded. It still flags a card original left in `Inbox` after its card was filed, and any number in anything the app writes: the database, records, logs, the activity CSV, results, prompts and filed copies. The app's own upload is the protected route for cards, because that photo never reaches Drive.

**One gate for raw card bytes.** `is_card_photo(sha256)` answers whether those bytes were, in any item and in any state (filed, gone, discarded), read as a card front. Every route that serves, moves or files a file's raw bytes asks it: the item file route, the document file route, the move to `Needs a look` (which asks in place instead), and the filer, which refuses raw bytes with a card's hash. The masked copy has its own hash and passes. A test lists every API route and public filer method and fails until each is classified, so a new route cannot skip the gate. Being a card is also sticky: once an item has been read as a card front it stays one, and it can be answered only as a card front or discarded. A copy found to share a card's hash is marked too.

**Numbers in other places.** After a card-area reading, any value in a field with 13 or more digits is masked, except the last four of the number that was read; a number split by up to three spaces, dots, slashes, hyphens or non-breaking spaces counts as one. Stored line text on card and unknown pages loses every run of three or more digits except a masked number's last four and a month and year. On card letters and statements, lines are masked by card shape (4-4-4-4, 4-6-5, 4-4-4-4-3, joined by up to three separator characters), with or without a valid Luhn check, so dates and amounts stay readable. A number glued to other digits keeps the last four of the number that was read, or nothing when none was read.

**Checks.** A leak scan runs over the vault, the database and the logs in the filing eval, with every card number, PDF password and the master password of the split as known secrets. I also opened `Secrets.kdbx` from a synthetic run in KeePassXC 2.8.0, where it showed the card entry and its two attachments.

## Alternatives considered
- **Secure the card before asking whose it is**: put the number in KeePass and swap in a masked copy first. It needs a KeePass entry before the owner is known, then a move, and new failure paths at the end of a milestone. Not taken.
- **Count a waiting original in the Inbox as a leak.** It would have forced the move above, for a file Drive already holds.
- **Guard each route as it is found.** That was rounds one to three. Each fix was right and each left another route, so the gate replaced it.
- **Mask digits before the type call.** The local type call can see a card back's CVV. Masking short digit runs on every page risks the type accuracy of all of them for a model that never leaves the Mac, so I recorded the exception instead.

## Consequences
Test run, synthetic set (`evals/results/2026-11-20_filing_test_b2a1fde.json`, and the same in `..._bcfd85d.json`): 0 secrets found by the leak scan, 0 values stored for CVV, 0 files left in `Inbox` apart from held ones, 0 waiting originals skipped.

Recorded limits:
- The local type call sees a card back's CVV, because only 13 to 19 digit runs are masked before it.
- A lone card back is filed without its CVV ever reaching KeePass, and a front and back that arrive as two Inbox files lose the CVV. Pairing them is a later feature. A lone back typed `other` can be served and moved to `Needs a look`, with its lines masked.
- A paper once read as a card front can be filed only as a card or discarded. A re-scan has a new hash, so it files normally.
- The gate knows a photo only after its first read stores a card reading, so an item still queued can be moved to `Needs a look` first. It is in Drive anyway.
- Shape masking misses OCR damage: a dropped digit, a letter read as a digit, groups of two digits, four or more separators, a number split across two lines. It also masks card-shaped ids such as a policy number printed as four groups of four.
- Reading a HEIC card writes one temporary unmasked copy in a private temp folder, deleted when the read ends. A kill at that moment can leave it there.
- Drive keeps deleted files in its trash for 30 days, and the README says so.
- The reading eval scores unmasked pages, so it cannot show what the line masking costs. Card pages are never searched by content (3).
