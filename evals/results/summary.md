# Results on eval-v1, test split

**Fields exactly right on photos: 99.7%**

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

## Filing (real worker, recorded readings)

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

Definitions of every measure are in `evals/README.md`. The numbers above are copied from the newest test results files in this folder.
