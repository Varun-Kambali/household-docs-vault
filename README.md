# household-docs-vault

Work in progress. A private document vault that runs on my Mac: it files bills, policies and IDs from one inbox, finds them from a short prompt, and reminds me before renewals.

[![CI](https://github.com/Varun-Kambali/household-docs-vault/actions/workflows/ci.yml/badge.svg)](https://github.com/Varun-Kambali/household-docs-vault/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE) · **[Case study](docs/case-study.md)**

[Demo GIF arrives with the last milestone.]

## Problem

A family's papers (insurance, warranties, IDs, home and vehicle papers, cards, medical records) arrive on paper and as invoices, and end up scattered. Finding one means digging, and nobody else knows what exists. Details are in the [case study](docs/case-study.md).

## Solution (planned for v1)

- Drop a document in one folder. The app reads it on the Mac with local models and files it under the right person in a Google Drive folder.
- Find any document from a short prompt, with the exact file, page and lines shown.
- See what exists, what is missing and what runs out soon, and get reminded before renewals.
- Turn a recorded doctor visit into a checkup document, and keep a medical history per person.
- Keep card details and passwords in an encrypted KeePass file.
- Fine-tune a small open-weight model for the field-reading step and measure it.

Every feature is in [docs/requirements.md](docs/requirements.md). The design is in [docs/architecture.md](docs/architecture.md).

## Results

Intake and reading (M2), scored on the test split of a synthetic set of 187 documents. Search, reminders and medical notes are later milestones and have no numbers yet.

Run 2026-11-20 on Apple M5, 16 GB, commit b2a1fde, 187 documents. Models: {"recorded_engines": ["ollama:qwen3-vl:4b"]}.

These numbers replay the committed recordings in `evals/recordings/eval-v1/test/` through this commit, with no model calls. The recordings hold long digit runs masked, so a field made of one (such as an acknowledgement number) scores as wrong on replay even when the live read was right. The seconds are the live run's.

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

### Filing (real worker, recorded readings)

| Measure | Result |
|---|---|
| Placement equals the decision | 100.0% |
| Exact copies caught | 100.0% |
| Wrong merges | 0 |
| Secrets found by the leak scan | 0 |
| Waiting originals skipped by it | 0 |
| Values stored for cvv | 0 |
| Undo then retry back to the same path | 100.0% |
| Files left in Inbox, apart from held ones | 0 |

Definitions of every measure are in `evals/README.md`. The numbers above are copied from `evals/results/summary.md`.

The reading numbers are a replay of the test run's recordings through the final code (`evals/results/2026-11-20_reading_test_b2a1fde.json`). The run itself, before the spelling snap, is `..._bcfd85d.json`: fields exactly right on photos 96.7%, person accuracy 92.4%, 0.00 silent misfiles. Both are on synthetic pages. The case study has the story: [docs/case-study.md](docs/case-study.md).

## Architecture

See [docs/architecture.md](docs/architecture.md) for the diagram, the data flow for one document and the threat table.

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Backend | Python, FastAPI, Pydantic | One language for the reader, the worker and the API, with typed models at every boundary |
| Storage | Files in a Drive-synced folder, SQLite on the Mac | [ADR 0002](docs/decisions/0002-files-live-in-google-drive.md), [ADR 0006](docs/decisions/0006-database-on-the-mac.md) |
| Secrets | KeePass file (KDBX4) | [ADR 0004](docs/decisions/0004-secrets-in-a-keepass-file.md) |
| Reading | Apple Vision text recognition (`ocrmac`) | [ADR 0008](docs/decisions/0008-reading-engine.md) |
| Field filling | qwen3-vl:4b through Ollama, on the page image | [ADR 0009](docs/decisions/0009-extraction-model-and-runtime.md) |
| Visit transcripts | Parakeet TDT 0.6B v2 (`parakeet-mlx`), medicine names checked | [ADR 0011](docs/decisions/0011-transcription-model.md) |
| Fine-tune | PyTorch, Transformers, PEFT; merged and converted to GGUF for Ollama | [ADR 0007](docs/decisions/0007-fine-tune-in-pytorch.md), [ADR 0010](docs/decisions/0010-fine-tune-path.md) |
| Frontend | React, TypeScript, Vite; types generated from the API's own description | Served by the API from one origin, with no fonts or scripts from anywhere else |

## Quickstart

```bash
git clone https://github.com/Varun-Kambali/household-docs-vault && cd household-docs-vault
cp .env.example .env
make setup
make test
make eval-smoke
```

The app is work in progress: the screens come in a later milestone, so for now it is an API and a worker.

## Usage

These commands work on the synthetic vault only (`VAULT_ROOT` in `.env`). The app mode (`vault run --app`) is for the installed app and reads the real folder from its own config file.

```bash
make vault        # copy twelve synthetic val documents into the synthetic Inbox
make run          # build the web app once, then serve it and the API on http://127.0.0.1:8710 and run the worker
uv run vault process                          # run the worker once over Inbox and print counts
uv run vault emergency-sheet --out sheet.html # the printable emergency sheet
```

While `make run` is up, the worker files what it can and puts the rest in `Needs a look`:

```bash
curl -s localhost:8710/v1/inbox/progress   # how far the batch is
curl -s localhost:8710/v1/activity         # what happened, newest first, with the buttons each row has
curl -s localhost:8710/v1/needs-a-look     # the questions waiting for an answer
```

The web app needs Node 26 (`web/.nvmrc`) to build. `make web` runs its dev server on http://127.0.0.1:5173 beside `make run`, and `make web-build` builds it again after a change.

Reading needs Ollama running with the two models in `.env.example`. Without it, files wait in `Inbox` and the worker tries again.

## Evaluation

The set is `evals/datasets/eval-v1`: 50 fictional document types (9 hand-drawn templates, 41 generic forms), each as a clean PDF, a phone photo and a scan, and a locked PDF for insurance papers and card statements. It is split by base document into `val` and `test`, both committed (187 documents each). Prompts and thresholds were tuned on `val`; `test` was scored once. Every document is synthetic: ID pages are marked `SPECIMEN` and the numbers fail their checksums or are the card networks' published test numbers. The measures and the filing eval are defined in `evals/README.md`; the choices are in [ADR 0016](docs/decisions/0016-synthetic-eval-set-v1.md).

```bash
make eval-smoke   # 22 val documents from committed recordings, no model, runs in CI
make eval         # the test split on real models (needs Ollama and the two models in .env.example; about 2 hours on an M5)
```

`make eval-smoke` fails if any number drops below `evals/thresholds.toml`. `make eval` writes a results file and `summary.md` into `evals/results/`.

## Testing

`make test` · `make lint` · `make web-test` · CI runs them, a browser accessibility check on every screen, builds the Docker image, runs the app in it with the stand-in reader and takes a PDF through the API.

## Deployment

The app is not deployed anywhere. It runs on one Mac, and the phone reaches it over Tailscale ([ADR 0001](docs/decisions/0001-runs-only-on-my-mac.md), [ADR 0005](docs/decisions/0005-phone-over-tailscale.md)). CI builds a Docker image and runs the app in it with the stand-in reader (no models), only to check the packaging and the API, because Docker on a Mac cannot use the GPU.

## Project structure

```
src/household_vault/   application code
web/                   the web app (Vite, React, TypeScript)
tests/                 fast tests, all model calls mocked
evals/                 eval-v1, recordings, results, thresholds
synth/                 the generator for the synthetic documents
docs/                  requirements, architecture, case study, decisions
```

## Design decisions

- [0001](docs/decisions/0001-runs-only-on-my-mac.md) The app runs only on my Mac.
- [0002](docs/decisions/0002-files-live-in-google-drive.md) Files live in Google Drive through the desktop app.
- [0003](docs/decisions/0003-search-not-chat.md) Search, not chat.
- [0004](docs/decisions/0004-secrets-in-a-keepass-file.md) Secrets go in a KeePass file.
- [0005](docs/decisions/0005-phone-over-tailscale.md) The phone reaches the app over Tailscale.
- [0006](docs/decisions/0006-database-on-the-mac.md) The database stays on the Mac.
- [0007](docs/decisions/0007-fine-tune-in-pytorch.md) The fine-tune uses PyTorch on a free GPU.
- [0008](docs/decisions/0008-reading-engine.md) Pages are read with Apple's built-in text recognition.
- [0009](docs/decisions/0009-extraction-model-and-runtime.md) Fields are filled by a small vision model reading the page image.
- [0010](docs/decisions/0010-fine-tune-path.md) The fine-tune path: LoRA in PyTorch, merged and converted to GGUF for Ollama.
- [0011](docs/decisions/0011-transcription-model.md) Visits are transcribed with Parakeet, and medicine names are checked before a note is saved.
- [0012](docs/decisions/0012-record-json-and-database.md) One record file per document, and a database on the Mac that the records can rebuild.
- [0013](docs/decisions/0013-who-owns-a-document-and-when-to-ask.md) Who owns a document, where it goes, and when the app asks instead.
- [0014](docs/decisions/0014-secrets-in-the-filing-pipeline.md) How secrets are kept out of everything the filing pipeline writes.
- [0015](docs/decisions/0015-document-type-from-text-and-title-cues.md) The document type comes from the page's text, and title cues only check the model.
- [0016](docs/decisions/0016-synthetic-eval-set-v1.md) A synthetic eval set of 50 document types, scored once on a held-out split.
- [0017](docs/decisions/0017-values-read-as-printed-and-the-spelling-snap.md) Values are read as printed and converted by code, and spelling slips are fixed from the page's own text.

## Limitations and next steps

- Every score is on synthetic pages. Real layouts differ, and the plan ends with a count-only check on my own documents.
- Test split of 187 documents: the 41 form types are one base document each, so a single odd document moves a type's score a lot.
- The test run came before the spelling snap, so the snap's numbers are a replay of the recordings. Long digit runs are masked in them, which scores one field type lower than the live read ([ADR 0017](docs/decisions/0017-values-read-as-printed-and-the-spelling-snap.md)).
- Filing a photo takes a median of 51 seconds and up to 112 on my Mac. It runs in the background.
- A card photo dropped in Drive's `Inbox` stays there until its question is answered, and Drive keeps deleted files in its trash for 30 days. More secrets limits are in [ADR 0014](docs/decisions/0014-secrets-in-the-filing-pipeline.md).
- English only, a single user, and the app needs the Mac to be awake for phone access.
- Next: search (M3). The screens, search, reminders, medical notes and the fine-tune are not built yet.

## What I learned

[Written after the first milestones.]

## License and data

MIT. All test and evaluation documents are synthetic and marked as specimens; their sources and licence will be listed here. No real document is in this repository.
