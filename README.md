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

| Metric | Baseline | This project | How measured |
|---|---|---|---|
| Document type accuracy | [baseline] | [value] | [`make eval`, `evals/results/...`] |
| Field F1 | [baseline] | [value] | [`make eval`, `evals/results/...`] |
| Silent misfiles per 100 documents | [baseline] | [value] | [`make eval`, `evals/results/...`] |
| Secrets found in stored files | [baseline] | [value] | [`make eval`, `evals/results/...`] |

## Architecture

See [docs/architecture.md](docs/architecture.md) for the diagram, the data flow for one document and the threat table.

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Backend | Python, FastAPI, Pydantic | [set when M2 starts] |
| Storage | Files in a Drive-synced folder, SQLite on the Mac | [ADR 0002](docs/decisions/0002-files-live-in-google-drive.md), [ADR 0006](docs/decisions/0006-database-on-the-mac.md) |
| Secrets | KeePass file (KDBX4) | [ADR 0004](docs/decisions/0004-secrets-in-a-keepass-file.md) |
| Reading | Apple Vision text recognition (`ocrmac`) | [ADR 0008](docs/decisions/0008-reading-engine.md) |
| Field filling | qwen3-vl:4b through Ollama, on the page image | [ADR 0009](docs/decisions/0009-extraction-model-and-runtime.md) |
| Visit transcripts | Parakeet TDT 0.6B v2 (`parakeet-mlx`), medicine names checked | [ADR 0011](docs/decisions/0011-transcription-model.md) |
| Fine-tune | PyTorch, Transformers, PEFT; merged and converted to GGUF for Ollama | [ADR 0007](docs/decisions/0007-fine-tune-in-pytorch.md), [ADR 0010](docs/decisions/0010-fine-tune-path.md) |
| Frontend | React, TypeScript, Vite | [set when M3 starts] |

## Quickstart

```bash
git clone https://github.com/Varun-Kambali/household-docs-vault && cd household-docs-vault
cp .env.example .env
make setup
make test
```

Until the app exists, `make test` is all there is to run.

## Usage

[Arrives with M2.]

## Evaluation

[Dataset, metrics and how to reproduce, from M2 on. Synthetic documents only.]

## Testing

`make test` · `make lint` · CI runs both and builds the Docker image.

## Deployment

The app is not deployed anywhere. It runs on one Mac, and the phone reaches it over Tailscale ([ADR 0001](docs/decisions/0001-runs-only-on-my-mac.md), [ADR 0005](docs/decisions/0005-phone-over-tailscale.md)). CI builds a Docker image only to check the packaging, because Docker on a Mac cannot use the GPU.

## Project structure

```
src/household_vault/   application code
tests/unit/            fast tests, all model calls mocked
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

## Limitations and next steps

[Filled in as milestones land. Known now: English only, a single user, and the app needs the Mac to be awake for phone access.]

## What I learned

[Written after the first milestones.]

## License and data

MIT. All test and evaluation documents are synthetic and marked as specimens; their sources and licence will be listed here. No real document is in this repository.
