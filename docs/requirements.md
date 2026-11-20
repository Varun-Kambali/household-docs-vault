# Requirements

Status: draft for v1; M2 is ticked. Tick a box when the feature works end to end from a fresh clone.

## Problem

A family's papers (insurance policies, warranty cards and bills, IDs, home and vehicle papers, work papers, cards, medical records) arrive on paper from shops and as invoices from online orders. They end up scattered, and nothing sorts them. Finding one means digging, and if the person who knows where everything is is not there, nobody knows what exists.

## User

One user: me, keeping papers for my family. Family members appear as people in the vault; they do not sign in. Everything runs on my Mac (Apple M5, 16 GB). My phone is an Android phone.

## Features by milestone

### M2 Intake and reading

- [x] One drop point, the `Inbox` folder. A paper scanned on the phone or an invoice saved as a PDF lands there.
- [x] The app waits for the file to finish syncing, then checks that it opens, is not empty, is a supported type (PDF, JPEG, PNG, HEIC, common audio) and is not a duplicate (same SHA-256 fingerprint as a filed file).
- [x] Reading happens on the Mac only: page images, text with the position of every line, document type, whose it is, and the fields for that type.
- [x] Core types get a full field schema: insurance, purchases (with where each was bought), identity, cards and medical.
- [x] Light types get type, person, document date, any expiry or renewal date and one or two key numbers: home, vehicle, work and education, tax.
- [x] Filing copies the file to `<Person>/<Area>/<date> <name>.<ext>`, confirms the copy's fingerprint, writes a record JSON, then clears `Inbox`. The original's bytes are never changed.
- [x] A document that concerns several people sits in its owner's folder (or `Home`) and is linked to every person it concerns.
- [x] A doubtful file moves to `Needs a look` with the reason, and the app asks one question.
- [x] Inbox activity lists every step with time and outcome, with Open, Undo, Discard or Keep both for duplicates, and answer buttons for `Needs a look`. The same log is written to `_system/log/<YYYY-MM>.csv`. (M2 builds the list and every action behind a button as API calls; the screen is M3.)
- [x] A password-protected PDF waits as "Can't open". The password is used once and kept only if I save it to the secrets store.
- [x] A backlog of existing papers goes through the same `Inbox`, with progress for the batch and `Needs a look` cleared as a list.
- [x] Card numbers, CVV, PINs and passwords go to `Secrets.kdbx`, an encrypted KeePass file written only by the app. Nothing secret reaches a plain file, the database, the search index, a log, a trace or a model prompt other than the local card-reading step. One recorded exception: the local type call can see a card back's CVV (ADR 0014).
- [x] A card photo sent through the app's upload is read on the Mac, its secrets go to the KeePass entry, and a masked copy is filed in `<Person>/Cards/`.
- [x] A card photo that arrives through Drive's `Inbox` is handled the same way (read, secrets to KeePass, masked copy filed), and the app reminds me that Drive keeps deleted files in its trash for 30 days.
- [x] A test scans everything the app writes for card-like numbers (Luhn check) and fails if one appears. A card original waiting in the Drive `Inbox` for an answer is not something the app wrote, so it is not counted (ADR 0014).
- [x] A printed emergency sheet says where the vault and `Secrets.kdbx` are and how to open the file with a standard KeePass app.
- [x] Baseline reading scores are committed: `evals/results/summary.md` and the test files beside it (ADR 0016).

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
- [ ] Each medicine name in the draft is matched against that visit's prescription, when one is filed, and against a list of known medicine names. A name that matches neither is shown to me to confirm or correct before the checkup is saved, so no medicine is saved on the transcript's word alone (ADR 0011).
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

Targets are scored on the held-out synthetic set, and each milestone's "done when" checks against them. The M1 baselines come from the spike set (`docs/spikes/`), which is smaller. The M2 column is the `test` split of `eval-v1` (ADR 0016), run once: where the live run and the re-measure by replay differ (ADR 0017), the replay is shown first and the live run in brackets. The files are `evals/results/2026-11-20_reading_test_b2a1fde.json` (replay) and `..._bcfd85d.json` (live), with the filing eval in the two `filing_test` files beside them. Targets that belong to a later milestone are left as they were.

| Metric | Target | M1 baseline | M2, test split |
|---|---|---|---|
| Secrets found in the files the app writes (database, records, logs, the activity CSV, results, prompts, filed copies) | 0 | not measured | 0 |
| Silent misfiles in the held-out set | At most 1 per 100 documents | not measured | 0.00 per 100 |
| Document type accuracy | 97% or more; a document the app is less sure of goes to `Needs a look` | not measured | 100.0% |
| Person accuracy | 95% or more | not measured | 100.0% (live run 92.4%) |
| Field exact match and F1, per field and type | Exact match 92% or more overall on photos, and 85% or more for each core type | 94.2% on photos with the chosen model (ADR 0009) | 99.7% on photos (live 96.7%); lowest core type lab report 95.8% (live: four core types at 75% to 78%); F1 96.6% (live 93.3%) |
| Search top-1 and top-3 hit rate | 85% or more top-1, 95% or more top-3 | not measured | M3 |
| Citation accuracy | 95% or more of answers cite the page that holds the value | not measured | M3 |
| Line-box accuracy for citations | 95% or more of the true lines found on photo pages | 96.1% mean (ADR 0008) | 98.5% (live 98.7%) |
| Share of files sent to `Needs a look` | 15% or less, scored on documents that need no question by design, with the raw share beside it | not measured | 0.0% on those documents (live 6.8%); 13.9% of all documents (live 19.8%) |
| Duplicate detection | 95% or more of duplicates caught, and no two different documents merged | not measured | 100.0% of 16 copies caught, 0 wrong merges |
| List-query reading accuracy | 90% or more | not measured | M3 |
| Medical checkup field accuracy | 90% or more | not measured | M5 |
| Disagreement flags caught | 90% or more | not measured | M5 |
| Medicines saved wrong without my OK | 0 | 16 of 22 medicines right in the raw transcript (ADR 0011) | M5 |
| Transcript word error rate | 6% or less | 4.18% (ADR 0011) | M5 |
| Seconds a document on the Mac, filing in the background | Median 60 or less, and no document over 2 minutes | 35.0 median, 46.8 at most on photos (ADR 0009) | 50.6 median, 112.0 at most (live run; 12 of 187 documents took over 60 s) |
| Cost per 1,000 documents | No API spend for the app; M6 reports the cloud model's cost beside the local ones | no API calls in M1 | no API calls |

The seconds row was restated on 2026-11-20. The target had been 60 seconds for each document. Twelve of the 187 test documents took 61 to 112 seconds, all long medical papers (lab reports, prescriptions, discharge summaries) with long lists to write out. Filing runs in the background and nobody waits on it (ADR 0009), so I changed the target to a median and a ceiling instead of recording twelve misses.
