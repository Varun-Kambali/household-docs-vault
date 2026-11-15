import json

from household_vault.doctypes import DocType
from household_vault.intake.sniff import FileKind
from household_vault.reading.cues import CueCheck
from household_vault.reading.engines import Engines, VisionPageReader
from household_vault.reading.pipeline import read_document
from household_vault.reading.source import DocumentSource, document_key
from tests.conftest import one_digit_changed, valid_aadhaar
from tests.fakes import FakeModels, FakeOcr


def read(source, ocr=None, models=None, mode="dev", **kw):
    engines = Engines(VisionPageReader(ocr or FakeOcr()), models or FakeModels())
    return read_document(source, "s", engines, mode=mode, **kw)


def test_a_long_pdf_sends_two_pages_and_keeps_all_text(five_page_scan_pdf):
    models = FakeModels(type_="health_policy", fill="{}")
    r = read(
        DocumentSource(FileKind.pdf, data=five_page_scan_pdf), FakeOcr(lines_per_page=12), models
    )
    assert len(r.pages) == 5 and models.fill_images == [2] and r.vision_pages == 2


def test_a_text_layer_skips_ocr_and_a_page_with_no_english_skips_the_models(clean_pdf_bytes, photo):
    ocr = FakeOcr()
    r = read(DocumentSource(FileKind.pdf, data=clean_pdf_bytes), ocr)
    assert (
        ocr.calls == 0 and "Policy schedule" in r.pages[0].lines[0].text + r.pages[0].lines[-1].text
    )
    models = FakeModels()
    assert (
        read(DocumentSource(FileKind.jpeg, data=photo), FakeOcr(lang="kn"), models).doc_type is None
    )
    assert models.calls == 0


def test_broken_json_is_retried_once_then_reported(photo):
    models = FakeModels(type_="health_policy", fill=["{not json", "{still not"])
    r = read(DocumentSource(FileKind.jpeg, data=photo), models=models)
    assert models.fill_calls == 2 and "_json" in r.issues and r.fields["policy_number"] is None
    other = read(DocumentSource(FileKind.jpeg, data=photo), models=FakeModels(type_="recipe"))
    assert other.doc_type is DocType.other


def test_a_good_second_answer_is_used(photo):
    models = FakeModels(type_="health_policy", fill=["{oops", '{"policy_number": "P/1/2"}'])
    r = read(DocumentSource(FileKind.jpeg, data=photo), models=models)
    assert (
        models.fill_calls == 2 and r.fields["policy_number"] == "P/1/2" and "_json" not in r.issues
    )
    assert set(r.seconds) >= {"read", "classify", "fill"}


def test_a_cue_conflict_is_reported(photo):
    r = read(
        DocumentSource(FileKind.jpeg, data=photo),
        FakeOcr(text="TAX INVOICE  GSTIN 29ABCDE"),
        FakeModels(type_="aadhaar"),
    )
    assert r.type_check == CueCheck("conflicts", DocType.tax_invoice)


def test_secret_values_never_reach_a_dump(photo):
    fill = '{"bank": "Nilgiri Bank", "number": "4111111111111111"}'
    r = read(
        DocumentSource(FileKind.jpeg, data=photo), models=FakeModels(type_="card_front", fill=fill)
    )
    assert r.secret_values["number"] == "4111111111111111"
    assert r.fields["number"] is None and r.fields["bank"] == "Nilgiri Bank"
    assert "4111111111111111" not in r.model_dump_json() + repr(r)
    assert "4111111111111111" in r.raw["fill"] and "raw" not in r.model_dump()


def test_the_type_call_never_sees_a_card_number(photo):
    models = FakeModels(type_="card_front", fill="{}")
    ocr = FakeOcr(text="4111 1111 1111 1111  VALID THRU 05/29")
    r = read(DocumentSource(FileKind.jpeg, data=photo), ocr, models)
    assert "XXXX XXXX XXXX 1111" in models.classify_text
    assert "4111 1111 1111 1111" not in models.classify_text
    assert "4111 1111 1111 1111" not in r.model_dump_json()
    # the fill call, the card-reading step, gets the text unmasked
    assert "4111 1111 1111 1111" in models.fill_texts[0]


def test_app_mode_reaches_the_checksum_rule(photo):
    fill = json.dumps({"holder": "Ravi Rao", "number": one_digit_changed(valid_aadhaar())})
    models = FakeModels(type_="aadhaar", fill=fill)
    assert read(DocumentSource(FileKind.jpeg, data=photo), models=models, mode="app").issues == {
        "number": "number may be misread"
    }
    assert read(DocumentSource(FileKind.jpeg, data=photo), models=models, mode="dev").issues == {}


def test_a_forced_type_skips_the_letter_check_and_the_type_call(photo):
    models = FakeModels(type_="pan", fill='{"holder": "A B"}')
    r = read(
        DocumentSource(FileKind.jpeg, data=photo),
        FakeOcr(lang="kn"),
        models,
        forced_type=DocType.aadhaar,
    )
    assert models.classify_calls == 0 and models.fill_calls == 1
    assert r.doc_type is DocType.aadhaar and r.type_check is None


def test_uploaded_images_are_read_without_a_file(photo):
    models = FakeModels(type_="health_policy")
    src = DocumentSource(FileKind.jpeg, images=[photo, photo, photo])
    r = read(src, models=models)
    assert len(r.pages) == 3 and models.fill_images == [2]


def test_other_is_not_filled(photo):
    models = FakeModels(type_="other")
    r = read(DocumentSource(FileKind.jpeg, data=photo), models=models)
    assert r.doc_type is DocType.other and models.fill_calls == 0 and r.fields == {}


def test_document_key():
    import hashlib

    one = hashlib.sha256(b"a").hexdigest()
    assert document_key([b"a"]) == one
    two = hashlib.sha256(b"b").hexdigest()
    assert document_key([b"a", b"b"]) == hashlib.sha256((one + two).encode()).hexdigest()


def test_stand_in_engines_read_a_text_layer_and_name_the_type(clean_pdf_bytes):
    from household_vault.config import load_settings
    from household_vault.reading.engines import make_engines

    engines = make_engines(load_settings(env={"VAULT_READER": "stand-in"}))
    r = read_document(DocumentSource(FileKind.pdf, data=clean_pdf_bytes), "s", engines, mode="dev")
    assert r.doc_type is DocType.health_policy and r.fields["policy_number"] is None
    assert r.engine == "stand-in"


def test_text_layer_lines_have_positions(clean_pdf_bytes):
    from household_vault.reading.render import text_layer

    width, height, lines = text_layer(clean_pdf_bytes, 0)
    assert (width, height) == (300, 400)
    first = next(ln for ln in lines if "Synthetic" in ln.text)
    assert 0.1 < first.bbox[0] < 0.2 and 0.1 < first.bbox[1] < 0.2 and first.bbox[3] > first.bbox[1]
