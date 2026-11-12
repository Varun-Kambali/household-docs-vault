# 0007. The fine-tune uses PyTorch on a free GPU
Date: 2026-11-11 · Status: accepted

## Context
The reason this project exists in my portfolio is to show fine-tuning an open-weight model and measuring the trade-off. Job listings that ask for it name PyTorch and LoRA. My Mac can train small models with MLX, but that is a smaller part of what those listings ask for. The task to tune is filling a JSON schema for the core document types, which is narrow and easy to score.

## Decision
I train with PyTorch, Hugging Face Transformers and PEFT (LoRA or QLoRA) on a free Colab or Kaggle GPU, using synthetic documents only, split into train, validation and a held-out test set that training never sees. The adapter is merged and converted for the local runtime on the Mac. The model I tune is the one that does the field-filling step; if the M1 spikes show a document model plus a text-only model beats a vision-language model, the text model is the one tuned. Base model, tuned model and a cloud model are compared on the held-out set: field exact match and F1 per field and type, latency per page on my Mac, and cost per 1,000 documents. The cloud model runs only on synthetic data, on demand. The winner serves the app, and a model card records data, settings, results and limits. Training on the Mac with MLX is an optional extra.

## Alternatives considered
- **Training on the Mac with MLX only.** Fits the machine but not the skill the listings ask for.
- **No fine-tune, prompting only.** Cheaper, but then the project shows nothing that the earlier ones do not.
- **A paid GPU.** Not needed for a small model; free tiers are enough.

## Consequences
Free GPU sessions are short and can be cut off, so training has to save checkpoints and the data pipeline has to be reproducible from the repo. The tuned model is only as good as the synthetic data is realistic, which the real-document check before v1.0.0 measures. A free-tier GPU's limits may force a smaller model than I would choose otherwise.
