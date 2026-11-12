COV_MIN ?= 80

.PHONY: setup spikes-setup lint test eval eval-smoke run docker

setup:
	uv sync
	uv run pre-commit install

# OCR engines for the reading spike. Needs macOS and `brew install tesseract`.
spikes-setup:
	uv sync --group spikes

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
