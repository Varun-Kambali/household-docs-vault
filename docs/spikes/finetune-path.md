# Fine-tune path spike: does LoRA training reach a running model on this Mac

## Question

Milestone 6 will LoRA-fine-tune a small open-weight model for field extraction. This spike does
not try to make a good model. It runs every step of that path once, on a tiny set, so a broken
step shows up now: prepare the data, train, merge the adapter, convert to GGUF, load the result
in Ollama (the Task 4 runtime) and extract one held-out document.

## Method

- Model: `Qwen/Qwen3-VL-2B-Instruct`, revision `89644892e4d85e24eaac8bacfd4f463576704203`,
  reading page images. The Task 4 doc (`extraction.md`) found the 4B and 8B vision models fill
  94 to 95% of fields but miss the 20 s limit, so a 2B vision model is the candidate worth
  training. Text-only Qwen3 models were not used.
- Data: the 36 pages of `evals/datasets/spike-v0`, split by document so a clean page and its
  photo twin always land together (`finetune/prepare.py`): 24 train, 6 validation, 6 test pages.
  The prompt is the Task 4 prompt (`PROMPT_VERSION` v1), imported, so training and inference
  see the same text. The answer is the ground-truth fields as JSON.
- Training (`finetune/train_lora.py`): PEFT LoRA, rank 8 (alpha 16, dropout 0.05) on the
  language model's attention and MLP projections, 20 steps at batch size 1, learning rate
  0.0002, bf16 on the Mac's MPS device, loss on the answer tokens only. Peak memory is two
  numbers: the process's resident memory (psutil, every 0.25 s) and the highest MPS driver
  allocation read after each step. Settings and library versions are in the results file.
- Merge: PEFT `merge_and_unload()` on the CPU in bf16, saved with the processor.
- Convert: llama.cpp's `convert_hf_to_gguf.py` at the commit that matches the Homebrew
  `llama.cpp` build, once for the language model (f16, then `llama-quantize` to Q4_K_M) and once
  with `--mmproj` for the vision projector. Steps are in `finetune/convert.md`.
- Load: `ollama create` from a Modelfile with two `FROM` lines (text GGUF, projector GGUF), then
  the first test-split page through `/api/chat` with the Task 4 prompt and schema, scored with
  `score_doc`. Ollama 0.40.16.
- Machine: Apple M5, 16 GB. Results: `finetune/results/2026-11-12_mac-mps_f67146f.json`. Memory
  figures below are MiB divided by 1024 (GiB).

## Results (Mac, MPS)

| Stage | Status | Seconds | Memory |
|---|---|---|---|
| prepare | ok | 0.5 | not meaningful (sub-second) |
| train, 786,432 px, 20 steps | ok | 400.4 | MPS peak 13.3 GiB, process resident 0.65 GiB |
| train, 1,310,720 px, stopped at the first step after a 600 s cap | failed after 14 of 20 steps | 657.9 | MPS peak 17.6 GiB, process resident 0.50 GiB |
| merge | ok | 5.6 | resident peak 4.6 GiB |
| convert (f16, projector, Q4_K_M) | ok | 30.1 | resident peak 2.3 GiB |
| import into Ollama | ok | 1.6 | n/a |
| load in Ollama | ok | 1.2 | server 2.5 GiB right after load |
| extract one held-out page | ok | 22.6 | server 4.2 GiB read once after the call |

**Image size is the limit on this Mac.** The first attempt used a longer image side
(1,310,720 pixels, about 1,280 image tokens). Its first seven steps took 8.2 to 21.9 s each, then
steps 8 to 14 took 53 to 129 s each and the MPS allocation went past the 16 GB of RAM (17.6 GiB),
so macOS was swapping. The 600 s cap is checked at the top of each step, so it stopped at the first step after it, 657.9 s in, after 14 steps; its record is kept. At 786,432
pixels (about 768 image tokens) all 20 steps finished: steps 1 to 7 took 6.4 to 8.4 s, but steps
8 to 20 took 9.0 to 53.0 s, so the run slowed here too, with a 13.3 GiB MPS peak. Training on
page images at this size works for 20 steps and is not a pace to plan hundreds of steps on.
Whether 768 image tokens is enough to read the small print on a page was not measured here.

**Loss.** The training loss went from 0.4855 at step 1 to 0.0184 at step 20. It is the loss on
the batch seen at that step, on 24 training pages, so it shows the loop learns and nothing about
how the model generalises.

**Merge and convert.** The merged model is 3.96 GiB of safetensors. The GGUF files are 3.21 GiB
(f16), 1.03 GiB (Q4_K_M) and 0.76 GiB (vision projector, f16). Qwen3-VL needed no special flags;
`--mmproj` writes the projector as its own file.

**Ollama.** Ollama accepted the text GGUF plus the projector GGUF as two `FROM` lines with no
template and no extra flags. `ollama show` listed the model as `qwen3vl`, with the `vision`
capability and a `clip` projector, and the chat template came from the GGUF (read in the
terminal, not recorded in the results file). The model loaded and answered through the same
`/api/chat` call and schema the Task 4 runner uses, with `think` set to false and no prefilled
think block, which this Instruct build did not need.

**One held-out document** (`tax_invoice-1-clean`, a test-split page; one document, not an
accuracy figure). The answer was valid JSON and 8 of 9 fields matched. The miss was
`seller_location`, returned as the full address block where the truth is the city. That is the
same miss every Task 4 candidate made on tax invoices (`extraction.md`, 0 of 4 pages). The 22.6 s
includes the first image encode after loading and is a single call, not a median.

## Colab T4

Pending. `finetune/colab_train.ipynb` clones the repo at commit
`a10f9ab1742cc2d63361053f1ebd3e8e5c2f2c7c`, builds the data itself, downloads the model, trains
the settings of the passing Mac run (same model, 786,432 px, rank 8, 20 steps) in fp16 instead of the Mac's bf16 (a free T4 has no bf16) and offers `adapter.zip` for download. The
owner runs it; the merge and conversion then run on the Mac with the same commands. Until it
runs, the fp16 path and the T4's time and memory are untested.

## What works end to end

Mac only, for 20 steps on page images at 786,432 pixels: prepare, train, merge, convert, import
and load all worked and a held-out page came back as schema-valid JSON. Colab T4 is untested.

## M6 training plan this implies

1. Train on Colab T4 if the notebook run confirms it fits; the Mac slowed after a few steps at
   the smallest image size tried. If Colab does not work, fall back to short Mac runs at 786,432
   pixels or fewer, or to a text-only model on Apple Vision text (the Task 3 pick), which was
   not tried here.
2. Keep the pipeline as built: prepare, train, merge on the Mac, convert with the pinned
   llama.cpp commit, import with two `FROM` lines. Re-check the pin when upgrading Ollama or
   llama.cpp, since Qwen3-VL conversion is recent.
3. Before training for real, fix the answer format. The ground-truth `fields` are all strings
   (amounts like `31990`, lists like `insured` joined with `; `), while the model answers with
   numbers and the scorer reads both. Train on the schema's own format so the model is not taught
   a format the prompt does not ask for.
4. Decide the image size by measuring field accuracy at 768 and more tokens, not by memory alone.
5. M6 needs a real train, validation and test set; 36 pages is a path check, not a dataset.

## Limits

- One run per configuration; no repeat, so the step times are one sample. The slowdown comes
  from memory pressure on this Mac and was not isolated further.
- Peak device memory is the MPS driver allocation read after each step, which can include cached
  buffers; process resident memory does not count MPS buffers. Ollama memory is a single reading
  of `ollama serve` and its children, not a peak.
- The held-out result is one page and no base-model comparison, so it says nothing about whether
  the 20 steps helped.
- The converter script comes from a shallow fetch of llama.cpp at one commit into the
  git-ignored `finetune/out/`; the Homebrew package ships only the binaries. Not tried: the
  llama.cpp CLI (`llama-mtmd-cli`), since Ollama loaded the model.
