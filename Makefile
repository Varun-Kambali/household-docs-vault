COV_MIN ?= 80

.PHONY: web web-build web-test eval-search-val eval-search search-set setup visits spikes-setup finetune-setup lint test eval eval-val eval-smoke run vault docker

setup: web/node_modules
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
	uv run pytest --cov=src --cov=synth --cov-fail-under=$(COV_MIN)

# Real models on the test split (scored once, at the end of M2), recorded, then the filing eval
# replays the recordings. Needs Ollama with the models pulled and the Mac's Apple Vision.
eval:
	@echo "make eval calls the local models for about 2 hours and needs Varun's yes first." >&2
	uv run python -m evals.runner reading --split test --engines mac --record evals/recordings/eval-v1/test
	uv run python -m evals.runner filing --split test --recordings evals/recordings/eval-v1/test

# The same on the val split, for tuning. The recordings stay out of git (var/ is ignored).
eval-val:
	@echo "make eval-val calls the local models for about 2 hours and needs Varun's yes first." >&2
	uv run python -m evals.runner reading --split val --engines mac --record var/recordings/val
	uv run python -m evals.runner filing --split val --recordings var/recordings/val

# The search eval set: the two extra document sets (clean variant, val and test) and the
# questions built from them and from eval-v1. Deterministic; no model.
search-set:
	uv run python -m vault_synth --set search-x1 --splits val,test --variants clean --out evals/datasets/search-v1/extra/search-x1
	uv run python -m vault_synth --set search-x2 --splits val,test --variants clean --out evals/datasets/search-v1/extra/search-x2
	uv run python -m evals.search_set

# The search eval on val, with the local models (qwen3:4b reads prompts, qwen3-embedding:0.6b
# makes vectors). VAL_RECORDINGS is the folder of val reading recordings (never committed). The
# readings and vectors are recorded under var/ and the results go to var/results-val.
VAL_RECORDINGS ?= var/recordings/val
eval-search-val:
	@echo "make eval-search-val calls the local models and needs Varun's yes first." >&2
	uv run python -m evals.runner search --split val --recordings $(VAL_RECORDINGS) --record var/recordings/search-val --results var/results-val

# The search eval on test: run once, at the end of M3.
eval-search:
	@echo "make eval-search calls the local models and needs Varun's yes first." >&2
	uv run python -m evals.runner search --split test --recordings evals/recordings/eval-v1/test --record var/recordings/search-test

# What CI runs: the committed smoke recordings, no model.
eval-smoke:
	uv run python -m evals.runner smoke

# The web app (web/). `make run` builds it once; `make web-build` builds it again after a change.
web/node_modules: web/package-lock.json
	cd web && npm ci
	touch web/node_modules

web/dist/index.html: web/node_modules
	cd web && npm run build

web-build:
	cd web && npm ci && npm run build

# The dev server on http://127.0.0.1:5173 with hot reload; it sends API calls to `make run`.
web:
	cd web && npm run dev

web-test: web/node_modules
	cd web && npm run lint && npm run format:check && npm run typecheck && npm run types:check && npm run test:coverage

run: web/dist/index.html
	uv run vault run

# Fills the synthetic Inbox with twelve val documents and writes the household file.
vault:
	uv run vault dev-vault --from evals/datasets/eval-v1 --split val --limit 12

docker:
	docker build -t household-docs-vault .
	docker run --rm household-docs-vault vault
	docker run --rm --entrypoint python household-docs-vault -c "import importlib, pkgutil, household_vault; [importlib.import_module(m.name) for m in pkgutil.walk_packages(household_vault.__path__, 'household_vault.')]; print('imported ok', household_vault.__version__)"
	@# the anonymous /data volume goes when the container stops
	@id=$$(docker run -d --rm -p 8710:8710 -v /data household-docs-vault); ok=1; \
	for i in $$(seq 1 30); do \
	  if curl -fs http://localhost:8710/healthz; then echo; ok=0; break; fi; sleep 1; done; \
	docker stop $$id >/dev/null; exit $$ok
