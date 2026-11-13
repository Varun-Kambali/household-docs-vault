COV_MIN ?= 80

.PHONY: setup visits spikes-setup finetune-setup lint test eval eval-smoke run docker

setup:
	uv sync
	uv run pre-commit install

# Renders the doctor-visit audio for the transcription spike with macOS `say` and ffmpeg.
# The audio is git-ignored (Apple's system-voice licence); scripts and truth are committed.
visits:
	uv run python -m vault_synth.visits --out evals/datasets/visits-v0

# OCR engines for the reading spike. Needs macOS and `brew install tesseract`.
spikes-setup:
	uv sync --group spikes

# torch, transformers and peft for the fine-tune path spike. Never part of `make setup` or CI.
finetune-setup:
	uv sync --group spikes --group finetune

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

test:
	uv run pytest --cov=src --cov-fail-under=$(COV_MIN)

eval:
	@echo "make eval: added in a later milestone" >&2; exit 1

eval-smoke:
	@echo "make eval-smoke: added in a later milestone" >&2; exit 1

run:
	@echo "make run: added in a later milestone" >&2; exit 1

docker:
	docker build -t household-docs-vault .
	docker run --rm household-docs-vault
