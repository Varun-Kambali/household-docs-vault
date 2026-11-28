# Case study: Household docs vault

Updated at the close of M3 (search). Every number comes from a results file in `evals/results/`; numbers for later milestones are still [brackets].

## Why: the problem
I keep my family's papers: insurance policies, warranty cards and bills, IDs, home and vehicle papers, work papers, cards and medical records. They arrive on paper from shops and as invoices from online orders, and they end up scattered. There is no single place to put them and nothing that sorts them, so finding one means digging.

The worst moment is not a lost warranty. An Instagram reel about families in India scrambling after a parent dies made it clear: nobody knows which policies, accounts and property papers exist, or where they are. Folders and Drive's own search do not solve that, because nothing reads the documents, nothing says what is missing, and nothing reminds anyone before a policy lapses.

## Why I built it
I wanted to solve that problem for my own family, and I wanted a project that shows a whole application, not one clever model call: document AI on local models, search that cites its source, privacy design for data I would never put on a hosted demo, and a real frontend. I also wanted to fine-tune an open-weight model and measure it honestly against the base model and a cloud model, which my other projects do not cover.

## What: the solution
I drop a document in one folder. The app reads it on my Mac, files it under the right person in a Google Drive folder, pulls out the fields that matter, and reminds me before anything runs out. I find any document from a short prompt, and the app shows the exact file, page and lines the answer came from. A recorded doctor visit becomes a checkup document, and each person gets a medical history document. Card details and passwords live in an encrypted file.

In scope for v1: insurance, purchases and warranties, identity papers and cards read in full; home, vehicle, work, education and tax papers read lightly (type, dates, key numbers); medical checkups and history; reminders; phone access. Out of scope: bank accounts, investments, loans and wills, other users signing in, languages other than English, and a hosted demo. I drew the line there so that the first version covers the papers I use most and can be finished and tested.

## Who and where: users and fit
The user is one person keeping papers for a family. Family members appear in the vault as people but do not sign in. It runs on one Mac, with the phone reaching it over a private network.

At a larger scale the same pipeline would need real users and permissions, a server instead of a laptop, and a way to share a vault between people. None of that is in v1.

## How: design and trade-offs
The app watches an `Inbox` folder, reads each file with local models, checks the output by code, and files the document in a folder that Google Drive for desktop syncs to the cloud. A SQLite database on the Mac, rebuildable from a record file per document, drives search and reminders. The diagram and data flow are in [docs/architecture.md](architecture.md).

The decisions that matter, each with the alternative that lost:

- **Runs only on my Mac.** No hosted demo, because the data is the point. [ADR 0001](decisions/0001-runs-only-on-my-mac.md).
- **Files live in Drive through the desktop app.** No Google Cloud project and no API code. [ADR 0002](decisions/0002-files-live-in-google-drive.md).
- **Search, not chat.** Short prompts that land on a file and a page. [ADR 0003](decisions/0003-search-not-chat.md).
- **Secrets in a KeePass file.** An open format with a master password, not home-made encryption. [ADR 0004](decisions/0004-secrets-in-a-keepass-file.md).
- **Phone over Tailscale.** Search away from the Mac without a public server. [ADR 0005](decisions/0005-phone-over-tailscale.md).
- **Database on the Mac.** Sync tools corrupt live database files. [ADR 0006](decisions/0006-database-on-the-mac.md).
- **Fine-tune in PyTorch.** I train the fine-tune in PyTorch with LoRA on a free Colab or Kaggle GPU, because that is what the job listings ask for. [ADR 0007](decisions/0007-fine-tune-in-pytorch.md).

The first milestone measured the models before any app code was written, each against a rule set before the run:

- **Reading pages with Apple's built-in text recognition.** It found 96.1% of the true lines on phone photos at 0.22 s a page. PaddleOCR was as accurate but took 10.8 s a page and 6.2 GB of memory. [ADR 0008](decisions/0008-reading-engine.md).
- **A vision model fills the fields.** qwen3-vl:4b reading the page image got 94.2% of fields exactly right on photos, against 86.7% for a text model reading the OCR output. The text model took 6.2 s a document against 35.0 s (medians), but filing runs in the background, so I took the accuracy. [ADR 0009](decisions/0009-extraction-model-and-runtime.md).
- **The fine-tune path works before the fine-tune.** A 20-step LoRA run on the Mac went all the way to a converted model that Ollama loads and that reads a held-out page, so M6 starts from a path that works. [ADR 0010](decisions/0010-fine-tune-path.md).
- **Medicine names are checked, not trusted.** Neither speech model got every medicine right in any of the five test visits, so a draft checkup's medicines are matched against the prescription and a list of known names, and I confirm the rest. [ADR 0011](decisions/0011-transcription-model.md).

Models only fill fixed schemas and code checks every output. Text inside a document is data and never an instruction.

M2 built the app from the Inbox to a filed document, and measured it on a synthetic set of 187 held-out test documents. The decisions from it:

- **One record file per document, and a database rebuildable from them.** The record sits in Drive next to the document, so it holds no secret and only masked line text. [ADR 0012](decisions/0012-record-json-and-database.md).
- **Ask rather than guess.** Each type has an owner rule and a list of required fields. A name that matches nobody, two people tied, a missing field or a type the title disagrees with makes the app ask one question. A marriage certificate that reads with one name asks, because the first validation run filed one silently. [ADR 0013](decisions/0013-who-owns-a-document-and-when-to-ask.md).
- **Secrets behind one gate.** I first guarded the places where the model should put a card number. The end-of-milestone review found it could put one anywhere, and fixing routes one by one took four rounds, each finding another way to the raw photo. Now one check on a file's SHA-256 is asked by every route that serves, moves or files raw bytes, and a test fails if a new route skips it. [ADR 0014](decisions/0014-secrets-in-the-filing-pipeline.md).
- **The type comes from the page's text, and title cues only check it.** A cue can send a document to a question, never pick its type. [ADR 0015](decisions/0015-document-type-from-text-and-title-cues.md).
- **A synthetic set split by base document**, tuned on one split and scored once on the other. [ADR 0016](decisions/0016-synthetic-eval-set-v1.md).
- **Read as printed, convert in code, snap spelling from the OCR text.** [ADR 0017](decisions/0017-values-read-as-printed-and-the-spelling-snap.md).

M3 built search and the screens, and measured them on a second synthetic set of 210 questions a split. The decisions from it:

- **The index lives in SQLite and the vectors are scanned exactly.** Keyword search over each document's stored lines and fields, `qwen3-embedding:0.6b` vectors held in memory, and reciprocal rank fusion, plus a ranking of its own for identifier-shaped words so an IMEI or a policy number is found by its digits. [ADR 0018](decisions/0018-the-search-index-in-sqlite.md).
- **The model reads the prompt, and code works out the rest.** `qwen3:4b` copies the prompt's words into slots; code decides who the people are, what the dates mean and which types are meant, from closed vocabularies. It is the same lesson as the spelling snap: the model points at words, and code converts them. I picked the 4 billion model over the 8 billion one because it was faster and smaller and, once code repaired the people slot, not less accurate. [ADR 0019](decisions/0019-the-model-reads-the-prompt-code-does-the-rest.md).
- **An answer is composed by code and shown only with a located line.** If no line on the page prints the value, or the question names someone outside the household, the app says there is no direct answer and shows the closest files. [ADR 0020](decisions/0020-answers-from-fields-with-a-located-line.md).
- **A search eval set, tuned on validation and scored once on test.** [ADR 0021](decisions/0021-the-search-v1-eval-set.md).
- **The app draws the page itself,** as a PNG from the server, so the viewer needs no PDF viewer and a card is drawn only from its masked copy. [ADR 0022](decisions/0022-the-apps-own-page-viewer.md).

The web app is React and TypeScript, served by the API from one origin with no outside fonts, scripts or images. I designed it from a written brief (calm, precise, private; looks like Preview and Finder, not a dashboard), and the reasons for each colour, type and spacing choice are in [docs/design-rationale.md](design-rationale.md). Two things changed in the build because I used the screens: the sidebar lists the twelve areas as one-click lists, so browsing needs no typing and no model, and the answer now says in words how the app read the question, so a misread shows.

How the search work went wrong first, and what I changed:
- The first search eval counted a find about an unknown person as declined, while the screen showed other members' files with no notice. The end-of-milestone review caught it, so the app now declines such a find and the eval reads only what the route returns.
- With the vectors off, keyword search found nothing for any prompt of two or more words, because it needed all the words in one line. I added an any-word fallback, ranked by BM25, that joins only when the vectors give no hits.
- My first fix for card numbers in a prompt also hid real IMEIs. Now only card-shaped runs are masked, and identifier fields are also indexed by their last four digits.
- The reading step took a month word out of a shop name ("Jan Aushadhi" read as January). The date backstop now skips words that belong to a stored place.

The tuning story, all on the validation split: the first run got 86.5% of photo fields exactly right against a target of 92%. 38 of the 72 misses were the model converting dates and amounts the app already knows how to parse, so I changed the prompt to copy them as printed and let code convert them (96.7%), then added a line to the type guide for lab reports mistaken for scan reports (97.6%). The rest were one-letter spelling slips in names that Apple Vision had read correctly, so after the test run I added a step that takes the OCR spelling when the model's value is a near match (99.4% on validation). That step was measured on the test split once, by replaying the recordings of the test run, with no model call.

## Results
Test split of eval-v1, 187 documents (59 clean PDFs, 59 photos, 59 scans, 10 locked PDFs). Copied from `evals/results/summary.md`, which replays the test run's committed recordings through the final code:

| Measure | Result |
|---|---|
| Type accuracy | 100.0% |
| Person accuracy (documents with a named person) | 100.0% |
| Fields exactly right, all documents | 99.4% |
| Fields exactly right, clean PDFs | 99.1% |
| Fields exactly right, scans | 99.4% |
| Fields exactly right, locked PDFs | 100.0% |
| Line recall on photos | 98.5% |
| Silent misfiles per 100 documents | 0.00 |
| Needs a look, documents that should file | 0.0% |
| Needs a look, all documents | 13.9% |
| Seconds per photo, median and maximum | 51.12 and 112.042 |

Filing, with the real worker and recorded readings: placement equals the decision on 100.0%, exact copies caught 100.0%, 0 wrong merges, 0 secrets found by the leak scan, 0 values stored for CVV.

What these numbers do not show. The test run itself was made before the spelling snap. The live numbers are lower on the same documents: fields exactly right on photos 96.7%, person accuracy 92.4%, silent misfiles still 0, and 19.8% of all documents asked about (`evals/results/2026-11-20_reading_test_bcfd85d.json`). Every person miss in the live run was a name the model misspelt, and the app asked about each one; none was filed wrong. The table above is the replay with the snap (`..._b2a1fde.json`), and it is a replay, so a field made of a long digit run (an acknowledgement number) scores wrong in it even where the live read was right. The seconds are the live run's: median 50.6 over all documents, 12 of 187 took over a minute (long medical lists), and the slowest took 112 seconds. Every number is on synthetic pages.

### Search (M3)

Test split of `search-v1`: 210 questions (100 lookups, 50 finds, 40 lists, 20 with no answer) on a vault of 177 synthetic documents. One live run on 2026-11-28, commit 93a99db, Apple M5 with 16 GB, `qwen3:4b` and `qwen3-embedding:0.6b`. The file is `evals/results/2026-11-28_search_test_93a99db.json`, and the recordings behind it are in `evals/recordings/search-v1/test/`. The reading prompt, the vocabulary and every threshold were tuned on the validation split, and this was the only run on the test split.

| Measure | Result |
|---|---|
| Right document first, lookups and finds (150) | 98.0% |
| Right document in the first three | 100.0% |
| Quick finder, right document in the first three | 94.7% |
| Lookups answered right (100) | 90.0% |
| Answers whose page and line are the true ones (91 answers) | 100.0% |
| Lists read into the right people, types, date field, range and place (40) | 82.5% |
| List rows, precision and recall | 81.4% and 87.5% |
| Questions with no answer that the app declined (20) | 85.0% |
| Answerable questions the app declined (150) | 8.7% |
| Seconds for a full search, median and 95th percentile | 3.24 and 3.84 |
| Seconds for the quick finder, median | 0.038 |
| Secrets found by the leak scan, search tables included | 0 |

Split by where the documents come from: the 31 lookups about `eval-v1` documents, which also depend on the M2 reading, are answered right 83.9% of the time, and the 69 about the extra documents 92.8%. The 14 list questions on the extra documents are read right 92.9% of the time and the 26 on `eval-v1` 76.9%. Five test prompts are also in validation (`seen_in_val`); all five were answered right, and every target still clears without them. Every search target in [requirements](requirements.md) passes.

What these numbers do not show. They are on synthetic documents and template-made questions, so they say how the app behaves on this kind of paper and prompt, not on mine. The first search after loading the model took 8.5 s, which a median hides. With Ollama off, the quick finder still works by keywords, but with the right document first for only 52.7% of lookups and finds and in the first three for 83.3%.

The targets are in [docs/requirements.md](requirements.md), with the M2 and M3 values beside each. Before v1.0.0 I will run the app on [20 to 30] of my own documents and publish counts only, never a value or a file name.

## Limits, and what better inputs would change
The scores are on synthetic documents, and real Indian layouts differ, so the real-document check at the end is what shows whether they hold. The 9 most-used types have hand-drawn templates; the other 41 share a generic form layout, and the test split holds one base document of each of those, so a single odd document moves a type's score a lot. The photos are the clean pages put through a perspective transform and blur in code, not taken with a phone. The type cues and guide were written with these forms in view, so 100% type accuracy says little about a real cover page.

The spelling snap works only when Apple Vision has the right spelling; where it does not, the app asks. The test re-measure was a replay, which masks long digit runs, so one field type scores lower there than it did live.

On secrets: a card photo dropped in Drive's `Inbox` stays there, as Drive holds it, until its question is answered, and I do not count that as a leak. A lone card back is filed without its CVV reaching KeePass. The local type call can see a card back's CVV. A paper once misread as a card front can only be filed as a card or discarded. Masking by card shape misses a number split across two lines or damaged by OCR, and it masks card-shaped policy numbers. Drive keeps deleted files in its trash for 30 days. The full list is in [ADR 0014](decisions/0014-secrets-in-the-filing-pipeline.md).

Search limits (M3), all measured or found in the review of the milestone:
- **Bare prompts can be read as a find instead of a list.** While tuning, the misses were mostly a lone place name after the word "documents" and a typo in the cue word ("poliies"). Seven of the 40 test lists missed on a wrong slot. The target is 80%, down from 90% (see [requirements](requirements.md)).
- **A bare outsider's name is not caught.** "Meera's PAN card" declines, because the possessive marks a person, but "Meera PAN card" does not, and may answer from a member's PAN. A rule that caught it made the app decline too many answerable questions.
- **The soft place filter.** Place, area and date range rank and shape a list but do not stop a lookup from answering. A shop the vault does not hold can be answered from another shop's invoice. I left it so a typo in a place does not decline an answerable question, and it goes to the next version of search.
- **The typing window for card numbers.** A card number typed into the box is masked once it is complete, but the digits before that reach the address bar and the quick search. Nothing is stored or logged.
- **Single-page development data.** The synthetic vault I used to check the screens has one page per document, so the viewer's lazy page loading for a long PDF is covered by a unit test and not by a live check.
- **The Inbox activity list is not yet one row per file,** and clicking a marked field in the viewer does not yet move the page to its line. Both wait for M4.
- **Synonyms need the vectors.** A word the page does not print ("fridge") is found only by the embedding model, and the keyword fallback misses it.

Documents are read in English only. Files in Drive are not encrypted, so someone who gets into my Google account can read them; only the secrets file is protected. The local models have to fit a 16 GB Mac, which caps how large a model the reader can use. Filing a photo takes a median of 51.1 s on my Mac and up to 112 s, because the vision model is slow on a full page. That is fine in the background but means a batch of papers takes minutes. Visits and medicine names (M5) are still measured on five synthetic recordings that are cleaner than a real clinic. A larger model or more real layouts would help, and the model can be swapped without touching the rest.

## What I learned
[Mine to write once there is something to learn.]
