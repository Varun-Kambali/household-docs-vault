import hashlib
import json
from pathlib import Path

import pytest

from household_vault.checks import luhn_valid
from household_vault.config import ConfigError, load_settings
from household_vault.doctypes import DocType
from household_vault.intake.sniff import FileKind
from household_vault.reading.engines import make_engines
from household_vault.reading.lines import Line, PageText
from household_vault.reading.ollama import ModelError, ModelUnavailable
from household_vault.reading.pipeline import read_document
from household_vault.reading.recorded import (
    Recording,
    RecordingRefused,
    recorded_engines,
    recorded_seconds,
    write_recording,
)
from household_vault.reading.source import DocumentSource

TEST_NUMBER = "5105105105105100"
KEY = hashlib.sha256(b"one document").hexdigest()


def not_a_test_number() -> str:
    """A 16-digit number that passes Luhn and is not a published test number."""
    body = "400000123456789"
    check = next(d for d in "0123456789" if luhn_valid(body + d))
    number = body + check
    assert number != TEST_NUMBER
    return number


def page(*texts: str) -> PageText:
    lines = [
        Line(text=t, bbox=(0.1, 0.1 + 0.1 * i, 0.9, 0.18 + 0.1 * i)) for i, t in enumerate(texts)
    ]
    return PageText(page=0, width=1000, height=1400, lines=lines)


def recording(**changes: object) -> Recording:
    values: dict[str, object] = {
        "key": KEY,
        "doc_id": "health_policy-1-clean",
        "pages": [
            page(
                "Care Health Insurance Limited Policy Schedule for the insured person",
                "Health Insurance policy number and the period of cover are printed here",
            )
        ],
        "classify_raw": json.dumps({"doc_type": "health_policy"}),
        "fill_raw": json.dumps({"insurer": "Care Health Insurance Limited"}),
        "seconds": {"read": 0.5, "classify": 1.5, "fill": 20.0},
        "engine": "ollama:qwen3-vl:4b",
        "prompt_version": "v2",
    }
    values.update(changes)
    return Recording.model_validate(values)


def test_a_recording_replays_through_the_reader(tmp_path: Path, clean_pdf_bytes: bytes) -> None:
    write_recording(tmp_path, recording())
    engines = recorded_engines(tmp_path)
    reading = read_document(
        DocumentSource(FileKind.pdf, data=clean_pdf_bytes), KEY, engines, mode="dev"
    )
    assert reading.doc_type is DocType.health_policy
    assert reading.fields["insurer"] == "Care Health Insurance Limited"
    assert reading.engine == "recorded"
    assert recorded_seconds(engines, KEY) == {"read": 0.5, "classify": 1.5, "fill": 20.0}


def test_a_missing_recording_is_model_unavailable(tmp_path: Path) -> None:
    engines = recorded_engines(tmp_path)
    with pytest.raises(ModelUnavailable, match="no recording"):
        engines.pages.read_pages(DocumentSource(FileKind.pdf, data=b""), KEY, None)
    with pytest.raises(ModelUnavailable, match="no recording"):
        engines.models.classify("text", KEY)


def test_an_answer_that_was_not_recorded_fails_again(tmp_path: Path) -> None:
    write_recording(tmp_path, recording(fill_raw=None))
    engines = recorded_engines(tmp_path)
    with pytest.raises(ModelError):
        engines.models.fill(DocType.health_policy, [], "", KEY)


def test_a_number_that_is_not_a_test_number_never_reaches_the_file(tmp_path: Path) -> None:
    other = not_a_test_number()
    grouped = " ".join(other[i : i + 4] for i in range(0, 16, 4))
    misread = other[:-1] + str((int(other[-1]) + 1) % 10)
    rec = recording(
        pages=[page(f"Card {grouped}", f"Card {TEST_NUMBER}", f"Misread {misread}")],
        fill_raw=json.dumps({"number": other, "again": misread, "test": TEST_NUMBER}),
    )
    write_recording(tmp_path, rec)
    text = (tmp_path / f"{KEY}.json").read_text()
    for digits in (other, grouped, misread):
        assert digits not in text
    assert text.count(TEST_NUMBER) == 2  # the published test number survives, in both places
    assert other[-4:] in text  # the last four stay, as everywhere else in the app


def test_writing_is_refused_in_app_mode(tmp_path: Path) -> None:
    with pytest.raises(RecordingRefused):
        write_recording(tmp_path, recording(), mode="app")
    assert list(tmp_path.iterdir()) == []


def test_a_key_that_is_not_a_hash_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        write_recording(tmp_path, recording(key="../escape"))


def test_make_engines_builds_the_recorded_reader(tmp_path: Path) -> None:
    write_recording(tmp_path, recording())
    settings = load_settings(env={"VAULT_READER": "recorded", "VAULT_RECORDINGS": str(tmp_path)})
    engines = make_engines(settings)
    assert engines.models.name == "recorded"
    with pytest.raises(ConfigError):
        make_engines(load_settings(env={"VAULT_READER": "recorded"}))
