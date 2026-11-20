# Results on eval-v1, test split

**Fields exactly right on photos: 96.7%**

Run 2026-11-20 on Apple M5, 16 GB, commit bcfd85d, 187 documents. Models: {"tags": {"qwen3-vl:4b": "a1b29c246319cdcb1f3842f36d29f198f737c0cf516ba1bcba34b1b974e87980", "qwen3:4b": "359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7"}}.

| Measure | Result |
|---|---|
| Type accuracy | 100.0% |
| Person accuracy (documents with a named person) | 92.4% |
| Fields exactly right, all documents | 96.1% |
| Fields exactly right, clean PDFs | 96.1% |
| Fields exactly right, scans | 96.4% |
| Fields exactly right, locked PDFs | 92.5% |
| Line recall on photos | 98.7% |
| Silent misfiles per 100 documents | 0.00 |
| Needs a look, documents that should file | 6.8% |
| Needs a look, all documents | 19.8% |
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
