# Case study: Household docs vault

Draft written at kickoff, before any code. Every number is a [bracket] until a results file in `evals/results/` holds it.

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

Models only fill fixed schemas and code checks every output. Text inside a document is data and never an instruction.

## Results
[Table copied from `evals/results/summary.md` once M2 produces it.]

The two targets set now: 0 secrets found anywhere the app writes, and at most 1 silent misfile per 100 documents in the held-out set. The other targets are set after the M1 spikes. Before v1.0.0 I will run the app on [20 to 30] of my own documents and publish counts only, never a value or a file name.

## Limits, and what better inputs would change
The app's tests and scores use synthetic documents, and real Indian layouts differ, so the real-document check at the end is what shows whether the scores hold. The local models have to fit a 16 GB Mac, which caps how large a model the reader can use. Documents are read in English only. Files in Drive are not encrypted, so someone who gets into my Google account can read them; only the secrets file is protected. Better inputs (more real layouts, a larger model) would help the reader, and the design lets the model be swapped without touching the rest.

## What I learned
[Mine to write once there is something to learn.]
