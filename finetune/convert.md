# Merge the adapter, convert to GGUF, load in Ollama

These are the steps the spike ran on the Mac, in order. Everything lands in `finetune/out/`
(git-ignored). Run them from the repository root. `make finetune-setup` installs the Python side.

Pinned for this spike: Qwen3-VL-2B-Instruct revision `89644892e4d85e24eaac8bacfd4f463576704203`,
llama.cpp commit `cd959bae99ff4bed22bef2604f45241c09bbb8c8` (the same commit as the Homebrew
`llama.cpp` 0.9.0 binaries), Ollama 0.40.16.

## 0. One-off setup

```sh
make finetune-setup
brew install llama.cpp                  # llama-quantize and llama-mtmd-cli
# The Homebrew package ships binaries only. The converter script lives in the source tree, so
# fetch that one commit (about 220 MB with history stripped) into the git-ignored out folder.
mkdir -p finetune/out && cd finetune/out
git init -q llama.cpp-src && cd llama.cpp-src
git remote add origin https://github.com/ggml-org/llama.cpp
git fetch -q --depth 1 origin cd959bae99ff4bed22bef2604f45241c09bbb8c8 && git checkout -q FETCH_HEAD
cd ../../..
# Base model weights, pinned
uv run --group finetune python -c "from huggingface_hub import snapshot_download; \
snapshot_download('Qwen/Qwen3-VL-2B-Instruct', revision='89644892e4d85e24eaac8bacfd4f463576704203', \
local_dir='finetune/out/base')"
```

## 1. Prepare, train, merge

```sh
uv run python -m finetune.stages run prepare -- uv run python -m finetune.prepare
uv run --group finetune python -m finetune.train_lora train --model finetune/out/base \
    --steps 20 --max-pixels 786432
uv run --group finetune python -m finetune.train_lora merge --model finetune/out/base
```

`merge` loads the base model on the CPU in bf16, applies the adapter with PEFT's
`merge_and_unload()` and saves the full model plus the processor to `finetune/out/merged/`.
Only the language model carries LoRA weights; the vision tower is the base model's.
A Colab adapter (`adapter.zip` from `colab_train.ipynb`) unzips into `finetune/out/adapter/` and
goes through the same merge command.

## 2. Convert to GGUF

llama.cpp's `convert_hf_to_gguf.py` writes the language model and, with `--mmproj`, the vision
projector as a second file. Qwen3-VL needs both. The text file is then quantised to Q4_K_M, the
quantisation the Task 4 candidates ran at.

```sh
cd finetune/out
export PYTHONPATH=llama.cpp-src/gguf-py
uv run --project ../.. --group finetune python llama.cpp-src/convert_hf_to_gguf.py \
    merged --outfile vault-f16.gguf --outtype f16
uv run --project ../.. --group finetune python llama.cpp-src/convert_hf_to_gguf.py \
    merged --mmproj --outfile mmproj-vault-f16.gguf --outtype f16
llama-quantize vault-f16.gguf vault-q4_k_m.gguf Q4_K_M
```

The spike ran these three commands as one stage with
`python -m finetune.stages run convert -- sh <script>` so they were timed together.

## 3. Import into Ollama and load

`finetune/out/Modelfile`:

```
FROM ./vault-q4_k_m.gguf
FROM ./mmproj-vault-f16.gguf
PARAMETER temperature 0
```

Two `FROM` lines, the text model first and the projector second: Ollama read the second file as
the projector (`ollama show` lists architecture `clip` and the `vision` capability) and took the
chat template from the GGUF.

```sh
ollama serve &                                   # plain process, never a service
uv run python -m finetune.stages run import -- ollama create vault-spike-qwen3vl-2b -f finetune/out/Modelfile
uv run --group spikes python -m finetune.extract_one --model vault-spike-qwen3vl-2b:latest
ollama rm vault-spike-qwen3vl-2b:latest          # then stop the server
```

`extract_one` takes the first document of the test split, sends its page image with the Task 4
prompt and the schema in `format`, and scores the answer with `score_doc`. Do not run training and
the Ollama server at the same time on a 16 GB Mac.

## 4. Record

```sh
uv run python -m finetune.stages collect --run mac-mps --settings finetune/out/settings.json
```

where `settings.json` is the run settings written by hand (model, revision, pixels, rank, steps,
library versions), writes `finetune/results/<date>_mac-mps_<commit>.json`.
