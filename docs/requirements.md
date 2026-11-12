# Requirements

Status: draft for v1. Tick a box when the feature works end to end from a fresh clone.

## Problem

A family's papers (insurance policies, warranty cards and bills, IDs, home and vehicle papers, work papers, cards, medical records) arrive on paper from shops and as invoices from online orders. They end up scattered, and nothing sorts them. Finding one means digging, and if the person who knows where everything is is not there, nobody knows what exists.

## User

One user: me, keeping papers for my family. Family members appear as people in the vault; they do not sign in. Everything runs on my Mac (Apple M5, 16 GB). My phone is an Android phone.

## Features by milestone

### M2 Intake and reading

- [ ] One drop point, the `Inbox` folder. A paper scanned on the phone or an invoice saved as a PDF lands there.
- [ ] The app waits for the file to finish syncing, then checks that it opens, is not empty, is a supported type (PDF, JPEG, PNG, HEIC, common audio) and is not a duplicate (same SHA-256 fingerprint as a filed file).
- [ ] Reading happens on the Mac only: page images, text with the position of every line, document type, whose it is, and the fields for that type.
- [ ] Core types get a full field schema: insurance, purchases (with where each was bought), identity, cards and medical.
- [ ] Light types get type, person, document date, any expiry or renewal date and one or two key numbers: home, vehicle, work and education, tax.
- [ ] Filing copies the file to `<Person>/<Area>/<date> <name>.<ext>`, confirms the copy's fingerprint, writes a record JSON, then clears `Inbox`. The original's bytes are never changed.
- [ ] A document that concerns several people sits in its owner's folder (or `Home`) and is linked to every person it concerns.
- [ ] A doubtful file moves to `Needs a look` with the reason, and the app asks one question.
- [ ] Inbox activity lists every step with time and outcome, with Open, Undo, Discard or Keep both for duplicates, and answer buttons for `Needs a look`. The same log is written to `_system/log/<YYYY-MM>.csv`.
- [ ] A password-protected PDF waits as "Can't open". The password is used once and kept only if I save it to the secrets store.
- [ ] A backlog of existing papers goes through the same `Inbox`, with progress for the batch and `Needs a look` cleared as a list.
- [ ] Card numbers, CVV, PINs and passwords go to `Secrets.kdbx`, an encrypted KeePass file written only by the app. Nothing secret reaches a plain file, the database, the search index, a log, a trace or a model prompt other than the local card-reading step.
- [ ] A card photo sent through the app's upload is read on the Mac, its secrets go to the KeePass entry, and a masked copy is filed in `<Person>/Cards/`.
- [ ] A card photo that arrives through Drive's `Inbox` is handled the same way (read, secrets to KeePass, masked copy filed), and the app reminds me that Drive keeps deleted files in its trash for 30 days.
- [ ] A test scans everything the app writes for card-like numbers (Luhn check) and fails if one appears.
- [ ] A printed emergency sheet says where the vault and `Secrets.kdbx` are and how to open the file with a standard KeePass app.
- [ ] Baseline reading scores are committed.

### M3 Search

- [ ] A search box is the home screen, and results update as I type. Every prompt stands alone; there is no thread.
- [ ] Answer beside the page: the answer on one side, the page on the other with the supporting lines outlined, the file path and page, Open at page and Show in folder.
- [ ] Quick finder: matching files as rows with type, person, key fields and path, with arrow keys, Enter to open and Cmd+Enter to show in the folder.
- [ ] Results of a list prompt sit in date order with path and a Remind me action.
- [ ] Show in folder reveals the file in Finder on the Mac and copies the Drive path on the phone. Open at page uses the app's own viewer on both.
- [ ] Adjustable sentence for lists: the app shows how it read the prompt ("Showing insurance and warranties for everyone that expire before 31 Mar 2027"), each part is a dropdown, and changing one updates the list without another model call.
- [ ] A local model turns the prompt into a structured query under a fixed JSON schema.
- [ ] Retrieval combines filters on extracted fields, keyword search over page text and vector search over page text.
- [ ] When the evidence is weak the app says "No direct answer" and shows the closest files.
- [ ] Secrets are never searched by content; a card's record can be found, and its secrets need the master password.
- [ ] ID numbers are shown masked (last 4 digits) until tapped.
- [ ] Search scores are committed.

### M4 Everyday views and phone

- [ ] What we have: one page per person, grouped by area, with what is expired, what runs out within a window (default 60 days), what is missing against a per-person checklist, and insurance with no nominee found.
- [ ] Each row shows status, key details, where the original paper is kept, where a login is kept, and the file path. These two locations are typed by hand.
- [ ] `<Person> - What we have.pdf` is written in that person's folder and rewritten when anything for that person changes.
- [ ] Reminders from extracted dates, with default lead times that can be changed (renewals, premium due, warranty and AMC end, passport, licence, RC and PUC, rent agreement, card expiry, card payment due, next checkup).
- [ ] Reminders reach me three ways: a Coming up list, a push notification to the installed phone app while the Mac is awake, and an Add to Google Calendar link that carries only a short title. Each reminder can be marked done or snoozed.
- [ ] The app listens on the Mac only and is published to my own devices with `tailscale serve`. On the phone it installs to the home screen.
- [ ] The app has its own sign-in (Argon2 password hash), sessions that expire, and a way to sign out a lost phone. Secrets ask for the master password on every reveal.
- [ ] Secrets are shown only after the master password, hidden again after 30 seconds, a copied secret is cleared from the clipboard after 30 seconds, and each reveal is logged without the value.
- [ ] Phone screens: search, document viewer, lists, Coming up, Inbox activity, What we have, checkups and history, recording upload.
- [ ] A launch agent starts the app when I log in to the Mac.
- [ ] The nightly copy of the app's database goes to `_system/backup/`.

### M5 Medical

- [ ] A recording of a doctor visit dropped in `Inbox` is filed under `<Person>/Medical/Recordings/`.
- [ ] The Mac transcribes it (English) with timestamps and writes a draft checkup: reason for visit, findings, medicines (name, dose, timing, duration, new or continued), tests before the next visit, next appointment, hospital, department, doctor. Every line links to its moment in the recording.
- [ ] If a prescription or report from the same day and person is filed, the app flags disagreements between it and the recording.
- [ ] I confirm or edit the draft. Only then is `Checkups/<date> <hospital> - <doctor>.pdf` written.
- [ ] `<Person> - Medical history.pdf` opens with allergies, ongoing conditions and medicines now, then every event oldest to newest with pictures of the report pages and the file path. It is rebuilt when a checkup is confirmed or a medical document is filed, and only from confirmed checkups and filed documents.
- [ ] The app never suggests a diagnosis, a dose or a treatment.
- [ ] Medical scores are committed.

### M6 Fine-tune

- [ ] A small open-weight model is fine-tuned with PyTorch, Transformers and PEFT (LoRA or QLoRA) on a free GPU for the field-filling step, using synthetic documents only, split into train, validation and a held-out test set.
- [ ] Base model, tuned model and a cloud model are compared on the held-out set: field exact match and F1 per field and type, latency per page on my Mac, cost per 1,000 documents.
- [ ] The winning local model serves the app, and a model card records data, training settings, results and limits.

### M7 Ship v1.0.0

- [ ] A fresh clone passes the README quickstart.
- [ ] The app has a check mode for my own documents. I run it on 20 to 30 of them and mark the type, the person and every field right or wrong. It writes a results file with counts only (per type and field: checked, right), never a value, name, number or file name. That file is committed.
- [ ] The README carries the security design and a demo GIF made on the synthetic vault.
- [ ] The case study carries the final numbers.

## Non-goals for v1

- Bank accounts, deposits, investments, loans, wills and nominations.
- Other users signing in, and sharing with family members.
- Hospital scan discs (DICOM). Scans arrive as phone photos and reports as phone scans.
- Languages other than English. A page with no English is filed and its fields are typed by hand.
- A hosted demo. The repo holds code and synthetic data only.

## Anti-goals

The project fails, even if it works, if:

- it is a chatbot. Every prompt stands alone;
- it files a document in the wrong place without saying so. Asking is better than guessing;
- any original file is edited, lost or overwritten;
- a card number, CVV, PIN or password appears in a plain file, a log, a trace, the search index or a model prompt;
- it gives medical advice. It records what was said and written, nothing more;
- any real document reaches this repository or a cloud model.

## Constraints

- Free tools only. No Google Cloud project. The only paid-API use is an opt-in comparison run on synthetic data.
- Local models must fit an M5 with 16 GB alongside the app. Docker on a Mac cannot use the GPU, so models run natively.
- Docker is not installed on my Mac; the image is built and checked in CI.
- Development works only on a synthetic vault inside the repo's test data. The real vault path lives only in the installed app's local config.
- Every number in the README comes from a committed results file.

## Success metrics

| Metric | Target |
|---|---|
| Secrets found in the database, index, logs, traces or Drive files | 0 |
| Silent misfiles in the held-out set | At most 1 per 100 documents |
| Document type accuracy | [set after M1 spikes] |
| Person accuracy | [set after M1 spikes] |
| Field exact match and F1, per field and type | [set after M1 spikes] |
| Search top-1 and top-3 hit rate | [set after M1 spikes] |
| Citation accuracy | [set after M1 spikes] |
| Line-box accuracy for citations | [set after M1 spikes] |
| Share of files sent to `Needs a look` | [set after M1 spikes] |
| Duplicate detection | [set after M1 spikes] |
| List-query reading accuracy | [set after M1 spikes] |
| Medical checkup field accuracy | [set after M1 spikes] |
| Disagreement flags caught | [set after M1 spikes] |
| Transcript word error rate | [set after M1 spikes] |
| Seconds per page on the Mac | [set after M1 spikes] |
| Cost per 1,000 documents | [set after M1 spikes] |
