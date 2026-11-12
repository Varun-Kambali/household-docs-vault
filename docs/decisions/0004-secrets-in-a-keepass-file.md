# 0004. Secrets go in a KeePass file
Date: 2026-11-11 · Status: accepted

## Context
I want card details and passwords in the vault: full card numbers, CVV, PINs and net-banking logins. The vault's files are plain (ADR 0002), so they cannot go there. My first plan was to keep only safe fields (bank, last 4 digits, expiry month) and never the secrets; I changed it because the point is to have everything in one place that the family can reach in an emergency.

## Decision
Secrets are kept in an encrypted KeePass database (KDBX4) inside the vault folder, written only by the app on the Mac and opened with a master password I choose. Secrets never go into plain files, the database, the search index, a log, a trace or a model prompt other than the local card-reading step. The app shows a secret only after the master password, hides it after 30 seconds, clears a copied secret from the clipboard after 30 seconds, and logs each reveal without the value. A card photo is kept as a protected attachment in its entry, and the copy filed in Drive is masked to the last 4 digits. A printed emergency sheet, kept with the original papers, says where the file is and how to open it with a standard KeePass app; I write the master password on it by hand. A test scans everything the app writes for card-like numbers and fails if it finds one.

## Alternatives considered
- **Safe fields only.** My first plan; it does not hold what I asked it to hold.
- **Home-made encryption.** No outside review and no other program can open it.
- **SQLCipher.** Nothing on a phone or in an emergency can read it.
- **Bitwarden.** Needs a cloud account or a server to run.

## Consequences
Google Drive cannot merge two edits of a KeePass file, so only the app on the Mac writes it, and edits from the phone go through the app. The format is open, so the family can open the file without the app. If the master password is lost, the secrets are lost; the emergency sheet is there to prevent that.
