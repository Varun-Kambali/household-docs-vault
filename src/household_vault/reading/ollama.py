"""A small client for a local Ollama. Only the two calls the reader needs."""

from __future__ import annotations

import base64
from typing import Any

import httpx


class ModelUnavailable(Exception):
    """Ollama is not running, or the model tag is not pulled."""


class ModelError(Exception):
    """Ollama answered with an error, or took too long."""


EMPTY_THINK = "<think>\n\n</think>\n\n"


class OllamaClient:
    def __init__(
        self,
        url: str,
        timeout_s: float = 300.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._http = httpx.Client(base_url=url, timeout=timeout_s, transport=transport)

    def tags(self) -> dict[str, str]:
        """Model name -> digest of every pulled model."""
        try:
            r = self._http.get("/api/tags")
        except httpx.TransportError as exc:
            raise ModelUnavailable("Ollama is not running") from exc
        if r.status_code != 200:
            raise ModelError(f"Ollama answered {r.status_code}")
        return {m["name"]: m.get("digest", "") for m in r.json().get("models", [])}

    def chat_json(
        self,
        model: str,
        system: str,
        user: str,
        images: list[bytes],
        schema: dict[str, Any],
        prefill_think: bool,
    ) -> str:
        message: dict[str, Any] = {"role": "user", "content": user}
        if images:
            message["images"] = [base64.b64encode(i).decode() for i in images]
        messages = [{"role": "system", "content": system}, message]
        if prefill_think:
            messages.append({"role": "assistant", "content": EMPTY_THINK})
        body = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": False,
            "format": schema,
            "keep_alive": "10m",
            "options": {"temperature": 0, "num_ctx": 12288, "num_predict": 1500},
        }
        try:
            r = self._http.post("/api/chat", json=body)
        except httpx.TimeoutException as exc:
            raise ModelError("the model took too long") from exc
        except httpx.TransportError as exc:
            raise ModelUnavailable("Ollama is not running") from exc
        # the status only: an error body could repeat the prompt
        if r.status_code == 404:
            raise ModelUnavailable(f"{model} is not pulled")
        if r.status_code != 200:
            raise ModelError(f"Ollama answered {r.status_code}")
        try:
            return str(r.json()["message"]["content"])
        except (ValueError, KeyError, TypeError) as exc:
            raise ModelError("Ollama answered with something unreadable") from exc
