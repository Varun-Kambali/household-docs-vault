"""Stand-ins for the reader's engines. No unit test calls Apple Vision, Ollama or the network."""

from __future__ import annotations

import io
import json
from collections.abc import Callable, Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import httpx
from PIL import Image
from pydantic import JsonValue
from vault_synth.model import SynthDoc
from vault_synth.sets import load_set, locked_password

from household_vault.db import Item
from household_vault.doctypes import DocType
from household_vault.filing.decide import decide
from household_vault.filing.questions import question_for
from household_vault.reading.lines import Line, PageText
from household_vault.reading.ollama import ModelUnavailable
from household_vault.reading.pipeline import Reading
from household_vault.reading.render import LockedPdfError
from household_vault.reading.source import DocumentSource, document_key

if TYPE_CHECKING:
    from household_vault.filing.filer import Filer

EVAL_V1 = Path(__file__).resolve().parents[1] / "evals" / "datasets" / "eval-v1"

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


# -- stand-ins that answer from the ground truth of the committed eval set ------------------------


def _index(docs: Sequence[SynthDoc], folder: Path) -> dict[str, SynthDoc]:
    """Every document by `document_key` of its files, and of each file alone."""
    found: dict[str, SynthDoc] = {}
    for doc in docs:
        files = [(folder / name).read_bytes() for name in doc.files]
        found[document_key(files)] = doc
        for data in files:
            found.setdefault(document_key([data]), doc)
    return found


@lru_cache(maxsize=1)
def _default_index() -> dict[str, SynthDoc]:
    docs = [d for d in load_set(EVAL_V1) if d.split in ("val", "test")]
    return _index(docs, EVAL_V1)


def _lookup(index: dict[str, SynthDoc], sha256: str) -> SynthDoc:
    try:
        return index[sha256]
    except KeyError:
        raise ValueError("no ground truth for this document") from None


class TruthPages:
    """A page reader that returns the truth lines of the document, found by its key. A locked
    document needs its password, as the real reader does."""

    def __init__(self, docs: Sequence[SynthDoc] | None = None, folder: Path | None = None) -> None:
        self._index = _default_index() if docs is None else _index(docs, folder or EVAL_V1)

    def read_pages(
        self, source: DocumentSource, sha256: str, password: str | None
    ) -> list[PageText]:
        doc = _lookup(self._index, sha256)
        if doc.variant == "locked" and password != locked_password(doc.base_id):
            raise LockedPdfError("the PDF needs a password")
        pages: dict[int, list[Line]] = {}
        for ln in doc.lines:
            pages.setdefault(ln.page, []).append(ln)
        return [
            PageText(page=n, width=1000, height=1400, lines=lines)
            for n, lines in sorted(pages.items())
        ]


class TruthModels:
    """Models that answer with the truth type and fields of the document, found by its key.

    `patch` replaces fields in every fill answer; `down_first` makes the first calls raise
    `ModelUnavailable`; `on_fill` runs at the start of each fill call.
    """

    name = "truth-models"

    def __init__(
        self,
        docs: Sequence[SynthDoc] | None = None,
        folder: Path | None = None,
        patch: Mapping[str, JsonValue] | None = None,
        down_first: int = 0,
    ) -> None:
        self._index = _default_index() if docs is None else _index(docs, folder or EVAL_V1)
        self.patch = dict(patch or {})
        self.down_first = down_first
        self.on_fill: Callable[[], None] | None = None
        self.calls = 0

    def _gate(self) -> None:
        self.calls += 1
        if self.down_first > 0:
            self.down_first -= 1
            raise ModelUnavailable("Ollama is not running")

    def classify(self, ocr_text: str, sha256: str) -> str:
        self._gate()
        return json.dumps({"doc_type": _lookup(self._index, sha256).doc_type.value})

    def fill(self, doc_type: DocType, images: list[bytes], ocr_text: str, sha256: str) -> str:
        self._gate()
        if self.on_fill is not None:
            self.on_fill()
        return json.dumps({**_lookup(self._index, sha256).fields, **self.patch})


def grey_jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 40), (128, 128, 128)).save(buf, format="JPEG")
    return buf.getvalue()


class OpenGateCards:
    """A card handler standing in for an open secrets store: it files a grey placeholder image
    for the card and removes the Inbox photo. `filer` is set by the world that uses it."""

    def __init__(self) -> None:
        self.filer: Filer | None = None

    def ready(self) -> bool:
        return True

    def handle(
        self,
        item: Item,
        reading: Reading,
        source: DocumentSource,
        origin: Literal["inbox", "upload"],
    ) -> Literal["filed", "waiting", "asked"]:
        from household_vault.worker import overrides_of

        assert self.filer is not None
        filer = self.filer
        decision = decide(
            reading,
            filer.household,
            filer.clock().date(),
            filer.store.documents_of_type(DocType.card_front),
            overrides_of(item),
        )
        if decision.outcome == "ask":
            question = question_for(decision.reasons, reading, filer.household, {})
            filer.to_needs_a_look(item, decision.reasons, question, reading)
            return "asked"
        filer.file_new(
            item,
            grey_jpeg(),
            "jpg",
            reading,
            decision,
            "fake-entry",
            {"last4": decision.last4},
        )
        filer.clear_card_photo(item.id)
        return "filed"
