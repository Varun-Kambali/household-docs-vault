import json
from pathlib import Path

import pytest

from evals.import_smoke import SmokeImportError, import_smoke, mask_recording, mask_text
from household_vault.leakscan import scan_text
from household_vault.reading.source import document_key

LUHN = "4000 0566 5566 5556"  # a Luhn-valid number that is not a published test card
TEST_CARD = "4111 1111 1111 1111"


def test_mask_text_keeps_the_last_four_and_the_separators():
    out, n = mask_text(f"Card {LUHN} valid")
    assert (out, n) == ("Card XXXX XXXX XXXX 5556 valid", 1)


def test_mask_text_leaves_published_test_cards_and_plain_text():
    assert mask_text(f"{TEST_CARD} on 12/03/2026") == (f"{TEST_CARD} on 12/03/2026", 0)


def test_mask_recording_counts_by_field_and_keeps_the_rest():
    body = {
        "sha256": "a" * 64,
        "doc_id": "d",
        "pages": [{"lines": [{"text": f"no {LUHN}", "page": 0}]}],
        "classify_raw": "{}",
        "fill_raw": json.dumps({"number": LUHN}),
        "engine": "ollama:x",
        "prompt_version": "v3",
    }
    out, counts = mask_recording(body)
    assert counts == {"pages.lines.text": 1, "fill_raw": 1}
    assert out["prompt_version"] == "v3" and out["engine"] == "ollama:x"
    assert scan_text(json.dumps(out), allow_test_cards=True) == []


def _recording(doc_id: str, text: str) -> dict:
    return {
        "sha256": document_key([doc_id.encode()]),
        "doc_id": doc_id,
        "pages": [
            {
                "page": 0,
                "width": 10,
                "height": 10,
                "lines": [{"text": text, "page": 0, "bbox": [0, 0, 1, 1]}],
            }
        ],
        "classify_raw": None,
        "fill_raw": None,
        "seconds": {},
        "engine": "ollama:x",
        "prompt_version": "v3",
    }


def _write(folder: Path, body: dict) -> None:
    folder.mkdir(exist_ok=True)
    (folder / f"{body['sha256']}.json").write_text(json.dumps(body))


def test_import_picks_ids_masks_and_keeps_the_recorded_version(tmp_path):
    src, dest = tmp_path / "src", tmp_path / "dest"
    _write(src, _recording("a-1", f"card {LUHN}"))
    _write(src, _recording("b-1", "plain"))
    _write(src, _recording("other", "not wanted"))
    counts = import_smoke(src, dest, ["a-1", "b-1"])
    assert dict(counts) == {"pages.lines.text": 1}
    assert len(list(dest.glob("*.json"))) == 2
    text = "".join(p.read_text() for p in dest.glob("*.json"))
    assert "5556" in text and "4000" not in text and '"prompt_version": "v3"' in text


def test_import_refuses_a_missing_or_doubled_document(tmp_path):
    src = tmp_path / "src"
    _write(src, _recording("a-1", "x"))
    with pytest.raises(SmokeImportError):
        import_smoke(src, tmp_path / "dest", ["a-1", "b-1"])
    twin = _recording("a-1", "y")
    twin["sha256"] = document_key([b"twin"])
    _write(src, twin)
    with pytest.raises(SmokeImportError):
        import_smoke(src, tmp_path / "dest", ["a-1"])
