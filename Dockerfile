# The web app, built once here and served by the API.
FROM node:26-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
RUN npm run build

FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-default-groups --no-install-project
COPY src ./src
RUN uv sync --frozen --no-default-groups --no-editable

FROM python:3.12-slim
RUN useradd --create-home --uid 1000 app
COPY --from=build --chown=app:app /app/.venv /app/.venv
COPY --from=web --chown=app:app /web/dist /app/web/dist
ENV PATH="/app/.venv/bin:$PATH"
# The image runs the whole app with the stand-in reader, to check the packaging and the API in CI.
# The real app runs natively on the Mac, because Docker on macOS cannot use the GPU or Apple Vision.
ENV VAULT_WEB_DIST=/app/web/dist \
    VAULT_READER=stand-in \
    VAULT_HOST=0.0.0.0 \
    VAULT_ROOT=/data/vault \
    VAULT_DB=/data/vault.db \
    VAULT_HOUSEHOLD=/data/household.json \
    VAULT_LOG_DIR=/data/logs
RUN mkdir /data && chown app:app /data
USER app
EXPOSE 8710
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8710/healthz', timeout=3)"]
CMD ["vault", "run"]
