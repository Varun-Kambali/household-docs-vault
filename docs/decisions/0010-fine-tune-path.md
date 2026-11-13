# 0010. The fine-tune path: LoRA in PyTorch, merged and converted to GGUF for Ollama
Date: 2026-11-13 · Status: accepted (Colab run pending)

## Context
0007 chose PyTorch, Transformers and PEFT for the fine-tune. M6 depends on every step of that path working on this setup, so M1 tried all of them once on a tiny run before any real training: prepare the data, train a LoRA adapter, merge it, convert the result for the runtime the app uses (Ollama, see 0009), load it, and read a held-out page. The run used Qwen3-VL-2B-Instruct on page images from the synthetic spike set, rank 8, 20 steps. Method and numbers: `docs/spikes/finetune-path.md`; results: `finetune/results/2026-11-12_mac-mps_f67146f.json`.

## Decision
The fine-tune path is:
1. `finetune/prepare.py` writes chat-format examples whose prompt is the extraction prompt itself, split by document so a page's clean and photo copies always land in the same split.
2. `finetune/train_lora.py` trains a LoRA adapter with Transformers and PEFT.
3. PEFT merges the adapter into the base model.
4. llama.cpp's converter writes a GGUF for the language model and a separate one for the vision projector, quantised to Q4_K_M. The converter script is not in the Homebrew package, so it comes from the llama.cpp source at the same commit.
5. Ollama imports the two GGUF files from a Modelfile with two `FROM` lines.

All five steps worked on the Mac: training at 786,432 pixels a page took 400.4 s for 20 steps with a 13.3 GiB GPU memory peak, and the converted model answered a held-out invoice page with valid JSON. Real training in M6 runs on a free Colab T4 through `finetune/colab_train.ipynb` once that notebook has been run; which base model M6 tunes follows 0009.

## Alternatives considered
- **Train on the Mac for M6.** It works for short runs only: at 1,310,720 pixels training went past the 16 GB of memory and swapped, and even at 786,432 pixels steps slowed from about 7 s to as much as 53 s after the first few.
- **Ollama's own adapter import** instead of merging and converting. Not tried; the merge and convert route is the one the llama.cpp and Ollama docs describe for this model family.
- **MLX for training and serving.** Not measured in M1 (0007 keeps it as an optional extra).

## Consequences
- The Colab T4 path (fp16, since a T4 has no bf16) is untested until I run the notebook; until then M6's plan rests on the Mac proof.
- The synthetic ground truth stores every field as text, amounts included, so the model learns to answer in strings. M2 moves the dataset to typed values before M6 trains for real.
- The one held-out page shows the path works, not how accurate a tuned model is; M6 measures that on the held-out set.
