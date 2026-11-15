import base64

import httpx
import pytest

from household_vault.doctypes import DocType
from household_vault.reading.engines import OllamaModels, prefill_for
from household_vault.reading.ollama import ModelError, ModelUnavailable, OllamaClient
from tests.fakes import FakeOllama

URL = "http://127.0.0.1:11434"
SCHEMA = {"type": "object"}


def test_fallback_model_when_the_vision_tag_is_missing():
    ollama = FakeOllama(tags={"qwen3:4b": "sha256:x"})
    m = OllamaModels(OllamaClient(URL, transport=ollama.transport), "qwen3-vl:4b", "qwen3:4b")
    m.fill(DocType.pan, [b"img"], "text", "s")
    assert (
        ollama.last_chat["model"] == "qwen3:4b" and "images" not in ollama.last_chat["messages"][-1]
    )
    assert "fallback" in m.name
    with pytest.raises(ModelUnavailable):
        OllamaClient(URL, transport=FakeOllama(down=True).transport).tags()


def test_prefill_only_for_thinking_vision_tags():
    assert prefill_for("qwen3-vl:4b")
    assert not prefill_for("qwen3-vl:4b-instruct")
    assert not prefill_for("qwen3:4b")


def test_the_vision_model_classifies_on_text_and_fills_from_images():
    ollama = FakeOllama(reply='{"doc_type": "pan"}')
    m = OllamaModels(OllamaClient(URL, transport=ollama.transport), "qwen3-vl:4b", "qwen3:4b")
    assert m.classify("INCOME TAX DEPARTMENT", "s") == '{"doc_type": "pan"}'
    chat = ollama.last_chat
    assert chat["model"] == "qwen3-vl:4b" and "images" not in chat["messages"][1]
    assert chat["messages"][-1]["content"].startswith("<think>")
    m.fill(DocType.pan, [b"img"], "text", "s")
    chat = ollama.last_chat
    assert chat["messages"][1]["images"] == [base64.b64encode(b"img").decode()]
    assert "name" in m.name or "qwen3-vl:4b" in m.name


def test_chat_options_are_pinned():
    ollama = FakeOllama()
    OllamaClient(URL, transport=ollama.transport).chat_json("m", "sys", "user", [], SCHEMA, False)
    body = ollama.last_chat
    assert body["stream"] is False and body["think"] is False and body["format"] == SCHEMA
    assert body["keep_alive"] == "10m"
    assert body["options"] == {"temperature": 0, "num_ctx": 12288, "num_predict": 1500}
    assert [m["role"] for m in body["messages"]] == ["system", "user"]


def test_errors_are_the_right_kind():
    client = OllamaClient(URL, transport=FakeOllama(status=500).transport)
    with pytest.raises(ModelError):
        client.chat_json("m", "s", "u", [], SCHEMA, False)
    with pytest.raises(ModelUnavailable):
        OllamaClient(URL, transport=FakeOllama(down=True).transport).chat_json(
            "m", "s", "u", [], SCHEMA, False
        )
    with pytest.raises(ModelUnavailable):
        OllamaClient(URL, transport=FakeOllama(status=404).transport).chat_json(
            "m", "s", "u", [], SCHEMA, False
        )

    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ModelError):
        OllamaClient(URL, transport=httpx.MockTransport(slow)).chat_json(
            "m", "s", "u", [], SCHEMA, False
        )


def test_neither_model_pulled_is_unavailable():
    ollama = FakeOllama(tags={"other:1b": "x"})
    m = OllamaModels(OllamaClient(URL, transport=ollama.transport), "qwen3-vl:4b", "qwen3:4b")
    with pytest.raises(ModelUnavailable):
        m.classify("text", "s")
