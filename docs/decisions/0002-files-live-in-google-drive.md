# 0002. Files live in Google Drive through the desktop app
Date: 2026-11-11 · Status: accepted

## Context
I open documents on my laptop and on my phone. Local disk alone gives no phone access. The Drive API would give programmatic access, but it needs a Google Cloud project for credentials, and a personal OAuth app left in testing mode has to sign in again every 7 days.

## Decision
The vault folder, `Family Vault`, sits inside the folder that Google Drive for desktop syncs. The app only reads and writes ordinary files on the Mac, and the Drive app copies them to Google Drive, where I open them on my phone. There is no Drive API code and no Google Cloud project. The folder is set to be available offline so the Mac always holds real files, not placeholders.

Files in Drive are left unencrypted so the Drive app on the phone can open them. The uploads have to be safe and logged: the app waits for a sync to finish, verifies each copy by fingerprint, never edits an original and logs every step.

## Alternatives considered
- **The Drive API with OAuth.** Needs a Google Cloud project and periodic re-authentication.
- **Local disk only.** No phone access.

## Consequences
Anyone who gets into my Google account can read the plain documents. That is a trade-off I accept for phone access; secrets are kept out of Drive's plain files (ADR 0004) and the README recommends 2-step verification. The app has to cope with sync delays and with Drive's conflict copies, which is why it waits for a file to settle before it reads it.
