# Extraction spike: which small local model fills a document's fields

## Question

After the reading step, the app fills a fixed set of fields per document type (policy number,
end date, sum insured and so on). This spike measures three small models on the synthetic set
`evals/datasets/spike-v0` (18 documents, each as a clean PDF and a phone-photo JPG, 36 pages in
all) and picks the one to build the extraction step on.

## Method

- Nine document types have a schema in `src/household_vault/schemas/`: health policy, vehicle
  policy, warranty card, tax invoice, Aadhaar, PAN, card front, prescription and lab report.
  Every field is optional. Dates are `datetime.date`, amounts are `Decimal`, and the medicine,
  lab test and warranty part lists hold small objects.
- One prompt (`PROMPT_VERSION` v1, in `spikes/extraction/prompt.py`) for all candidates. The
  system text says to fill only what is printed, to use null for anything absent, to write
  dates as YYYY-MM-DD and amounts as plain numbers. The user text names the document type and
  gives the schema as JSON Schema. The same schema goes to Ollama's `format` parameter, so the
  output is constrained to it. Temperature 0, context 12,288 tokens, at most 1,500 output tokens.
- Vision candidates get the page image: the PDF rendered at 200 dpi with pypdfium2, or the JPG
  as is. The text candidate gets the lines Apple Vision reads (the Task 3 pick), joined top to
  bottom, with lines on the same row joined left to right. The text candidate's seconds include
  that OCR read (0.2 s per page); OCR for the whole set runs once, before the model loads.
- Candidates run through Ollama 0.40.16 only, called over HTTP on localhost (`/api/chat`). MLX
  is not measured. One model is loaded at a time and unloaded (`keep_alive: 0`) before the next.
  The model loads before the first document, so the load is not in the seconds per document.
- Qwen3 thinking. The `qwen3-vl` tags are the thinking builds and `think: false` does not stop
  them: in a probe on one card page, with output capped, the whole budget went to thinking and
  no answer came back. For the candidates whose tag contains `-vl`, the runner sends an empty
  think block (`<think></think>`) as the last assistant message, after the user message. That the
  models then returned valid JSON on all 36 pages is the only evidence that they continued from
  it; nothing further is claimed. `qwen3:4b` honours `think: false`. These are the means used to switch thinking off in each candidate.
- Quantisation: all three default tags are Q4_K_M. The results files do not record it; it comes
  from the tags' model metadata in the local Ollama store (`file_type`).
- Scoring (`spikes/extraction/score.py`): a field is correct when the model's value, read through
  the schema, equals the ground truth read the same way. Dates compare by value (ISO,
  `dd/mm/yyyy`, `dd-mm-yyyy` and `14 Mar 2024` are accepted). Amounts compare as numbers after
  removing the rupee sign, `Rs.`, commas, spaces and a percent sign. Lists (`insured`,
  `medicines`, `tests`, `warranty_parts`) compare as sets of normalised items. Other text
  compares with case, extra spacing and commas ignored; commas are ignored because the printed
  address wraps over lines without them while the ground truth has them. Extra keys are ignored.
  A missing or null field is wrong. JSON valid means the output parses as a JSON object.
- Memory figures are in GiB (MiB divided by 1024). Peak memory is the highest resident set size seen, sampled every 0.25 s with psutil, of the
  `ollama serve` process plus its child processes, which is where the model runs. It is the
  server's memory, not the Python script's. The idle server before loading used 14 to 28 MB
  in the three runs (`baseline_rss_mb`). The
  loaded size is what `ollama ps` reports for the model with a 12,288-token context.
- Machine: Apple M5, 16 GB. Commit bb03fb8. Raw per-document outputs and scores are in
  `spikes/extraction/results/`.
- Command: `make spikes-setup`, start `ollama serve`, then
  `uv run --group spikes python -m spikes.extraction.run --set evals/datasets/spike-v0`.

## Results

Field exact match is correct fields over all fields: 120 per variant (18 documents). Seconds
are per document.

| Candidate | Input | Digest | Variant | Field exact match | JSON valid | Median s | Max s | Peak memory (GiB) | Loaded size (GiB) |
|---|---|---|---|---|---|---|---|---|---|
| qwen3:4b | Apple Vision text | 359d7dd4bcda | clean | 87.5% (105/120) | 100% | 6.5 | 12.5 | 5.8 GiB | 4.2 GiB |
| qwen3:4b | Apple Vision text | 359d7dd4bcda | photo | 86.7% (104/120) | 100% | 6.2 | 11.8 | 5.8 GiB | 4.2 GiB |
| qwen3-vl:4b | page image | a1b29c246319 | clean | 95.0% (114/120) | 100% | 40.2 | 46.6 | 6.5 GiB | 4.6 GiB |
| qwen3-vl:4b | page image | a1b29c246319 | photo | 94.2% (113/120) | 100% | 35.0 | 46.8 | 6.5 GiB | 4.6 GiB |
| qwen3-vl:8b | page image | 9cf69da2b16d | clean | 95.8% (115/120) | 100% | 63.9 | 80.2 | 8.4 GiB | 6.8 GiB |
| qwen3-vl:8b | page image | 9cf69da2b16d | photo | 95.0% (114/120) | 100% | 65.4 | 76.1 | 8.4 GiB | 6.8 GiB |

Photo field exact match by document type (6 to 10 fields per type, two documents each, so one
miss moves a type by 10 to 17 points):

| Document type | qwen3:4b | qwen3-vl:4b | qwen3-vl:8b |
|---|---|---|---|
| aadhaar | 87.5% | 87.5% | 100% |
| card_front | 100% | 100% | 100% |
| health_policy | 90.0% | 100% | 100% |
| lab_report | 75.0% | 100% | 100% |
| pan | 62.5% | 100% | 100% |
| prescription | 83.3% | 83.3% | 83.3% |
| tax_invoice | 83.3% | 77.8% | 77.8% |
| vehicle_policy | 95.0% | 100% | 100% |
| warranty_card | 87.5% | 100% | 100% |

The two vision models read slowly on this machine. The longest prompt was 4,436 tokens
for the vision models (a page image plus the schema) and 636 tokens for `qwen3:4b` on OCR text
(`max_prompt_tokens` in the results files).
Settings that might speed the vision models up were not tried (smaller render size, Ollama's
flash attention setting, a lower context).

## The pick

The rule: best overall field exact match on photo documents among candidates at or under 20 s
per document and under 10 GiB peak memory.

- `qwen3-vl:8b`: 95.0% on photos, but 65.4 s median and 76.1 s at most. Fails the time limit.
- `qwen3-vl:4b`: 94.2% on photos, but 35.0 s median and 46.8 s at most. Fails the time limit.
- `qwen3:4b` on Apple Vision text: 86.7% on photos, 6.2 s median, 11.8 s at most, 5.8 GiB peak.
  Meets both limits.

**Pick: `qwen3:4b` reading the Apple Vision text, run through Ollama.** It is the only
candidate inside the limits. It is also the weakest on accuracy, 7.5 to 8.3 points behind the
vision models on photos, and most of that gap is on three document types (below), so the next
milestone starts by closing it.

## Runtime

Ollama is the runtime for the pick. It loaded and unloaded each model on request, accepted the
JSON Schema in `format`, and kept all three models inside the 16 GB of memory, one at a time. MLX was not
measured. It is the alternative to consider when serving is built (M6): it may read a full page
faster than Ollama did here, which would put a vision model back inside the 20 s limit, and
it would need its own memory and output-format checks.

## Where the pick goes wrong

These are the fields `qwen3:4b` got wrong on at least one of the four pages of a type (two
documents, clean and photo). The next milestone's schema and prompt work starts from this list.
Counts are correct pages out of four.

| Document type | Field | Correct | What went wrong |
|---|---|---|---|
| prescription | medicines | 0/4 | Kept the form's `Tab ` prefix in the name (`Tab Cetirizine`); the ground truth omits it. The vision models did the same, so this is a prompt rule to add |
| lab_report | tests | 0/4 | Haemoglobin read as 122 instead of 12.2 on one clean page; on the others the unit came back as `H lakh/cumm` because the printed high flag `H` was folded into the unit |
| health_policy | policyholder | 0/4 | The model inserted a colon inside the name (`Yash:asvi Dalal`). The OCR text for the page is correct, so this is the model, not the reader |
| tax_invoice | seller_location | 0/4 | Returned the whole address block; the ground truth is the city. The vision models did the same. The schema field needs a description |
| pan | holder, father_name | 2/4 each | Dropped the surname on the clean page (`NITARA` for `NITARA DATE`) |
| pan | date_of_birth | 2/4 | Read `27/1.10.1958` on the clean page |
| aadhaar | number | 2/4 | Dropped the spaces (`486157821135`); the ground truth keeps the printed grouping |
| warranty_card | product, model | 2/4 each | Stray characters on photos (`2: 25 L`, `KD- 43X889`) |
| tax_invoice | model | 3/4 | `WW80576N` for `WW80576FN` (dropped a letter) |
| vehicle_policy | policy_number | 2/4 | Inserted a space (`0/0 0/000`) on photos |

The fields the two vision models also get wrong (so they are not caused by the text path):
prescription `medicines` (0/4, same `Tab ` prefix; the 8B model also put the dose in the name
on one page), tax_invoice `seller_location` (0/4), tax_invoice `model` (3/4), tax_invoice
`invoice_date` (2/4, `20032025` returned for `2025-03-20`) and, for the 4B model, aadhaar
`number` (2/4, spaces dropped). Card front reached 100% on every candidate.

## Limits

- 18 documents per variant, two per document type, from one generator and one seed. A type's
  rate moves 10 to 17 points on a single miss, and the ranking of candidates close together (the
  two vision models, 94.2% and 95.0%) is not settled by this set.
- The documents are synthetic and in English. The Kannada lines are drawn without shaping, so
  they are not scored; the set has no Hindi lines.
- Prompt v1 was not tuned. Several misses above (the `Tab ` prefix, the city) come from the
  prompt and schema, and would move every candidate.
- Time is for one document at a time with the model already loaded. A cold load adds time that
  is not in these numbers.
- Memory is the Ollama server's resident memory. Ollama's model files are mapped and may be
  counted partly in resident memory and partly not, so the loaded size is given beside it.
