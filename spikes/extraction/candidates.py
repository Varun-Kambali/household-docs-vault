"""Extraction candidates. Each one fills a document's fields from the page image or from OCR text.

Ollama is called over HTTP on localhost (POST /api/chat, `format` = JSON Schema, `think` = false,
`keep_alive` = 0 to unload). httpx and psutil load inside the methods that need them, so the
module imports without the spikes group.
"""

from __future__ import annotations

import base64
import contextlib
from pathlib import Path
from typing import Any, Literal

from spikes.extraction.prompt import SYSTEM, user_prompt

OLLAMA_URL = "http://localhost:11434"
NUM_CTX = 12288  # a 200 dpi A4 page is about 4,000 image tokens, plus schema and answer
NUM_PREDICT = 1500
REQUEST_TIMEOUT_S = 300.0


class CandidateUnavailable(Exception):
    """The model is not pulled, or the runtime is not running."""


class Candidate:
    def __init__(
        self, name: str, runtime: Literal["ollama", "mlx"], kind: Literal["vision", "text"]
    ) -> None:
        self.name = name
        self.runtime = runtime
        self.kind = kind
        self.digest: str | None = None
        self.runtime_version: str | None = None
        self.max_prompt_tokens = 0

    def load(self) -> None:
        raise NotImplementedError

    def extract(self, doc_files: list[Path], ocr_text: str | None, schema_json: str) -> str:
        raise NotImplementedError

    def unload(self) -> None:
        raise NotImplementedError

    def rss_mb(self) -> float | None:
        """Resident memory of whatever holds the model, sampled while it runs."""
        return None

    def loaded_size_mb(self) -> float | None:
        return None


def _server_processes() -> list[Any]:
    """The `ollama serve` process and its children (the model runner is a child process)."""
    import psutil

    found = []
    for p in psutil.process_iter(["name", "cmdline"]):
        cmd = p.info["cmdline"] or []
        if p.info["name"] == "ollama" and "serve" in cmd[1:2]:
            found.append(p)
    procs = []
    for server in found:
        procs.append(server)
        procs.extend(server.children(recursive=True))
    return procs


class OllamaCandidate(Candidate):
    """kind="vision" sends the page image; kind="text" sends OCR text only."""

    # Qwen3 and Qwen3-VL Instruct builds do not think; the flag is still sent so a build that does
    # (the plain `qwen3:4b` tag may) answers straight away.
    def __init__(self, model: str, kind: Literal["vision", "text"], doc_type: str = "") -> None:
        super().__init__(name=model, runtime="ollama", kind=kind)
        self.model = model
        self.doc_type = doc_type

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        import httpx

        r = httpx.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=REQUEST_TIMEOUT_S)
        if r.status_code != 200:
            raise RuntimeError(f"ollama {r.status_code}: {r.text[:300]}")
        return r.json()  # type: ignore[no-any-return]

    def load(self) -> None:
        import httpx

        try:
            tags = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=10).json()
            self.runtime_version = httpx.get(f"{OLLAMA_URL}/api/version", timeout=10).json()[
                "version"
            ]
        except httpx.HTTPError as exc:
            raise CandidateUnavailable(f"ollama is not running: {exc}") from exc
        match = [m for m in tags.get("models", []) if m["name"] == self.model]
        if not match:
            raise CandidateUnavailable(f"{self.model} is not pulled")
        self.digest = match[0]["digest"]
        # A chat call with no messages loads the model and returns; keep_alive holds it for the run.
        self._post({"model": self.model, "messages": [], "stream": False, "keep_alive": "30m"})

    def extract(self, doc_files: list[Path], ocr_text: str | None, schema_json: str) -> str:
        message: dict[str, Any] = {
            "role": "user",
            "content": user_prompt(self.doc_type, schema_json, ocr_text),
        }
        if self.kind == "vision":
            message["images"] = [base64.b64encode(f.read_bytes()).decode() for f in doc_files]
        import json

        resp = self._post(
            {
                "model": self.model,
                "messages": [{"role": "system", "content": SYSTEM}, message],
                "stream": False,
                "think": False,
                "format": json.loads(schema_json),
                "keep_alive": "30m",
                "options": {"temperature": 0, "num_ctx": NUM_CTX, "num_predict": NUM_PREDICT},
            }
        )
        self.max_prompt_tokens = max(self.max_prompt_tokens, resp.get("prompt_eval_count", 0))
        return str(resp["message"]["content"])

    def unload(self) -> None:
        import httpx

        with contextlib.suppress(httpx.HTTPError, RuntimeError):
            self._post({"model": self.model, "messages": [], "stream": False, "keep_alive": 0})

    def rss_mb(self) -> float | None:
        import psutil

        total = 0
        for p in _server_processes():
            try:
                total += p.memory_info().rss
            except psutil.NoSuchProcess:
                continue
        return total / 1024 / 1024 if total else None

    def loaded_size_mb(self) -> float | None:
        import httpx

        for m in httpx.get(f"{OLLAMA_URL}/api/ps", timeout=10).json().get("models", []):
            if m["name"] == self.model:
                return float(m["size"]) / 1024 / 1024
        return None


CANDIDATES: dict[str, tuple[str, str]] = {
    "qwen3-vl:4b": ("ollama", "vision"),
    "qwen3-vl:8b": ("ollama", "vision"),
    "qwen3:4b": ("ollama", "text"),
}
