"""Stand-ins for the reader's engines. No unit test calls Apple Vision, Ollama or the network."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import httpx
from PIL import Image

from household_vault.doctypes import DocType
from household_vault.reading.lines import Line

FILLER = "Synthetic specimen page used by the reader tests"


class FakeOcr:
    """Returns `lines_per_page` lines per page: `text` (if given) first, then English filler.

    The filler keeps a page above the reader's English-letter minimum. `lang` marks every line.
    """

    name = "fake-ocr"

    def __init__(self, text: str | None = None, lines_per_page: int = 3, lang: str = "en") -> None:
        self.text = text
        self.lines_per_page = lines_per_page
        self.lang = lang
        self.calls = 0

    def read(self, image: Image.Image, page: int) -> list[Line]:
        self.calls += 1
        texts = [self.text] if self.text else []
        texts += [f"{FILLER} {i}" for i in range(self.lines_per_page - len(texts))]
        return [
            Line(
                text=t,
                page=page,
                bbox=(0.05, 0.05 + 0.06 * i, 0.9, 0.09 + 0.06 * i),
                lang=self.lang,  # type: ignore[arg-type]
            )
            for i, t in enumerate(texts)
        ]


def _queue(value: str | Sequence[str]) -> list[str]:
    return [value] if isinstance(value, str) else list(value)


class FakeModels:
    """`type_` and `fill` are one answer or a list used in turn (the last one repeats)."""

    name = "fake-models"

    def __init__(
        self, type_: str | Sequence[str] = "other", fill: str | Sequence[str] = "{}"
    ) -> None:
        self._types = _queue(type_)
        self._fills = _queue(fill)
        self.classify_calls = 0
        self.fill_calls = 0
        self.classify_text = ""
        self.fill_images: list[int] = []
        self.fill_texts: list[str] = []

    @property
    def calls(self) -> int:
        return self.classify_calls + self.fill_calls

    def classify(self, ocr_text: str, sha256: str) -> str:
        self.classify_text = ocr_text
        answer = self._types[min(self.classify_calls, len(self._types) - 1)]
        self.classify_calls += 1
        return json.dumps({"doc_type": answer})

    def fill(self, doc_type: DocType, images: list[bytes], ocr_text: str, sha256: str) -> str:
        self.fill_images.append(len(images))
        self.fill_texts.append(ocr_text)
        answer = self._fills[min(self.fill_calls, len(self._fills) - 1)]
        self.fill_calls += 1
        return answer


class FakeOllama:
    """A fake Ollama server on httpx.MockTransport. `last_chat` is the last /api/chat body."""

    def __init__(
        self,
        tags: dict[str, str] | None = None,
        reply: str = "{}",
        down: bool = False,
        status: int = 200,
    ) -> None:
        self.tags = (
            tags if tags is not None else {"qwen3-vl:4b": "sha256:v", "qwen3:4b": "sha256:t"}
        )
        self.reply = reply
        self.down = down
        self.status = status
        self.last_chat: dict[str, Any] = {}
        self.chats = 0
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("refused", request=request)
        if request.url.path == "/api/tags":
            models = [{"name": n, "digest": d} for n, d in self.tags.items()]
            return httpx.Response(200, json={"models": models})
        if request.url.path == "/api/chat":
            self.last_chat = json.loads(request.content)
            self.chats += 1
            if self.status != 200:
                return httpx.Response(self.status, text="error")
            return httpx.Response(
                200, json={"message": {"role": "assistant", "content": self.reply}}
            )
        return httpx.Response(404)
