# 0009. Fields are filled by a small vision model reading the page image
Date: 2026-11-13 · Status: accepted

## Context
After a page is read (0008), the app fills a fixed set of fields for its document type: policy number, end date, sum insured and so on. The M1 spike ran three local models through Ollama on the synthetic spike set (18 documents, each as a clean PDF and a phone photo), with one untuned prompt and the type's JSON schema passed as Ollama's output format. The rule set before the run was the best field exact match on photos among models at or under 20 s a document and under 10 GiB of memory. Method and numbers: `docs/spikes/extraction.md`; results: `spikes/extraction/results/2026-11-12_*_bb03fb8.json`.

| Model | Input | Fields exactly right, photos | Median seconds a document | Peak memory |
|---|---|---|---|---|
| qwen3:4b | Apple Vision text | 86.7% | 6.2 | 5.8 GiB |
| qwen3-vl:4b | page image | 94.2% | 35.0 | 6.5 GiB |
| qwen3-vl:8b | page image | 95.0% | 65.4 | 8.4 GiB |

By that rule the text model won, as the only one under 20 s. The 20 s limit was a guess made before the spike, though, and filing runs in the background after I drop a file in the Inbox, so nobody waits on it.

## Decision
I fill fields with qwen3-vl:4b reading the page image, through Ollama, using the default Q4_K_M build. Filing has no 20 s limit; the targets allow up to 60 s a document, and the spike's slowest photo took 46.8 s. Apple Vision (0008) still supplies the text and line boxes that search and citations use, and every model output is still checked against its schema and by code. In M6 the fine-tune tries to bring the 2B vision model up to this accuracy so filing gets faster.

## Alternatives considered
- **qwen3:4b on the OCR text.** 6.2 s a document against 35.0 s, but 7.5 points fewer fields right on photos; the largest gaps are on PAN cards (62.5% against 100%) and lab reports (75.0% against 100%). It stays as the fallback if the vision model cannot run.
- **qwen3-vl:8b.** One more field right out of 120 on photos, for 65.4 s a document against 35.0 s and 8.4 GiB of memory against 6.5 GiB. Two documents per type cannot separate the two vision models.
- **Text model first, vision model only when a field is missing or fails a check.** Faster on easy pages, but a second model path to build, test and keep in memory. Worth revisiting only if filing time becomes a problem.
- **MLX instead of Ollama.** Not measured in M1.

## Consequences
- Ollama's qwen3-vl tags are thinking builds that ignore `think: false`, so each request ends with an empty think block as the last assistant message. Valid JSON on all 36 pages is the only evidence that this works. An Instruct build would avoid the workaround; it is a separate download, to ask about in M2.
- A batch of ten documents takes several minutes. The app files one document at a time, so the models fit in 16 GB, and shows each file's progress.
- The untuned prompt gets some fields wrong for every model (the `Tab ` prefix on medicines, the invoice city, the invoice date format), so M2's prompt and schema work starts there.
- Two documents per type is too few to rank close candidates, so M2's full eval set measures the pick again.
