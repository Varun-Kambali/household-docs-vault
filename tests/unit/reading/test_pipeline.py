import json

import pytest

from household_vault.doctypes import DocType
from household_vault.intake.sniff import FileKind
from household_vault.reading.cues import CueCheck
from household_vault.reading.engines import Engines, VisionPageReader
from household_vault.reading.ollama import ModelError, ModelUnavailable
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
    # one digit misread, so the number fails Luhn: only the any-long-run mask catches it
    models = FakeModels(type_="card_front", fill="{}")
    ocr = FakeOcr(text="4111 1111 1111 1112  VALID THRU 05/29")
    r = read(DocumentSource(FileKind.jpeg, data=photo), ocr, models)
    assert "XXXX XXXX XXXX 1112" in models.classify_text
    assert "4111 1111 1111 1112" not in models.classify_text
    assert "4111 1111 1111 1112" not in r.model_dump_json() + repr(r)
    # the fill call, the card-reading step, gets the text unmasked
    assert "4111 1111 1111 1112" in models.fill_texts[0]


def test_a_card_photo_with_a_misread_digit_is_masked_in_the_stored_pages(photo):
    models = FakeModels(type_="card_front", fill="{}")
    r = read(
        DocumentSource(FileKind.jpeg, data=photo),
        FakeOcr(text="4111 1111 1111 1112"),
        models,
    )
    assert "1111 1111 1112" not in r.model_dump_json() + repr(r)
    assert "XXXX XXXX XXXX XXXX" in " ".join(ln.text for ln in r.pages[0].lines)


def test_a_page_with_no_type_masks_every_long_run_in_its_lines(photo):
    r = read(
        DocumentSource(FileKind.jpeg, data=photo), FakeOcr(lang="kn", text="4111 1111 1111 1112")
    )
    assert r.doc_type is None
    assert "1111 1111 1112" not in r.model_dump_json() + repr(r)


def test_a_policy_number_that_is_not_a_card_stays_readable(photo):
    from vault_synth.checks import luhn_valid

    number = "4111111111111112"
    assert not luhn_valid(number)
    r = read(
        DocumentSource(FileKind.jpeg, data=photo),
        FakeOcr(text=f"Policy number {number}"),
        FakeModels(type_="health_policy"),
    )
    assert number in " ".join(ln.text for ln in r.pages[0].lines)


def test_a_broken_type_answer_is_retried_once(photo, monkeypatch):
    models = FakeModels(type_=["health_policy"], fill="{}")
    answers = iter(["{broken", json.dumps({"doc_type": "health_policy"})])
    monkeypatch.setattr(models, "classify", lambda text, sha: (_count(models), next(answers))[1])
    r = read(DocumentSource(FileKind.jpeg, data=photo), models=models)
    assert models.classify_calls == 2 and r.doc_type is DocType.health_policy


def _count(models):
    models.classify_calls += 1


def test_the_fill_renders_pdf_pages_at_200_dpi(five_page_scan_pdf, monkeypatch):
    from household_vault.reading import pipeline

    seen = []
    real = pipeline.render_page

    def spy(data, index, **kwargs):
        seen.append(kwargs.get("dpi"))
        return real(data, index, **kwargs)

    monkeypatch.setattr(pipeline, "render_page", spy)
    read(
        DocumentSource(FileKind.pdf, data=five_page_scan_pdf),
        models=FakeModels(type_="health_policy"),
    )
    assert seen == [200, 200]


@pytest.mark.parametrize("which", ["classify", "fill"])
def test_a_model_that_is_down_propagates(photo, monkeypatch, which):
    models = FakeModels(type_="health_policy")

    def down(*args, **kwargs):
        raise ModelUnavailable("down")

    monkeypatch.setattr(models, which, down)
    with pytest.raises(ModelUnavailable):
        read(DocumentSource(FileKind.jpeg, data=photo), models=models)


def test_two_failed_type_calls_leave_the_type_open(photo, monkeypatch):
    models = FakeModels()

    def fail(*args, **kwargs):
        raise ModelError("slow")

    monkeypatch.setattr(models, "classify", fail)
    r = read(DocumentSource(FileKind.jpeg, data=photo), models=models)
    assert r.doc_type is None and "_json" in r.issues and models.fill_calls == 0
    assert r.type_check is None


def test_a_heic_photo_is_converted_once(photo, monkeypatch):
    from household_vault.reading import engines, pipeline

    calls = []

    def convert(data):
        calls.append(1)
        return photo

    monkeypatch.setattr(engines, "heic_to_png", convert)
    monkeypatch.setattr(pipeline, "heic_to_png", convert)
    models = FakeModels(type_="health_policy")
    read(DocumentSource(FileKind.heic, data=b"heic"), models=models)
    assert len(calls) == 1 and models.fill_images == [1]


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


@pytest.mark.parametrize("answer", ["other", "recipe"])
def test_an_other_page_masks_a_misread_card_number(photo, answer):
    r = read(
        DocumentSource(FileKind.jpeg, data=photo),
        FakeOcr(text="4111 1111 1111 1112"),
        FakeModels(type_=answer),
    )
    assert r.doc_type is DocType.other
    assert "1111 1111 1112" not in r.model_dump_json() + repr(r)


def test_a_forced_other_masks_a_misread_card_number(photo):
    r = read(
        DocumentSource(FileKind.jpeg, data=photo),
        FakeOcr(text="4111 1111 1111 1112"),
        forced_type=DocType.other,
    )
    assert "1111 1111 1112" not in r.model_dump_json() + repr(r)


_CARD_NUMBER = "4111 1111 1111 1111"  # a published test number


def _fields_of(photo, type_, fill, text="Deccan Trust Bank welcome"):
    models = FakeModels(type_=type_, fill=json.dumps(fill))
    return read(DocumentSource(FileKind.jpeg, data=photo), FakeOcr(text=text), models)


def test_a_full_number_in_a_card_letter_field_keeps_only_the_last_four(photo):
    r = _fields_of(photo, "card_welcome_letter", {"bank": "Deccan", "last4": _CARD_NUMBER})
    assert r.fields["last4"] == "1111"
    assert "4111" not in json.dumps(r.fields)


def test_last4_with_fewer_than_four_digits_is_dropped(photo):
    r = _fields_of(photo, "card_statement", {"bank": "Deccan", "last4": "12"})
    assert r.fields["last4"] is None


def test_a_full_number_in_a_card_front_text_field_is_masked(photo):
    r = _fields_of(
        photo, "card_front", {"number": _CARD_NUMBER, "card_name": _CARD_NUMBER, "bank": "Deccan"}
    )
    dumped = json.dumps(r.fields)
    assert _CARD_NUMBER not in dumped and "4111111111111111" not in dumped
    assert r.fields["card_name"] == "XXXX XXXX XXXX 1111"
    assert r.secret_values["number"]  # the real number still reaches the card step


def test_the_read_cvv_is_blanked_wherever_it_appears_as_a_token(photo):
    r = _fields_of(
        photo, "card_front", {"bank": "Deccan 123 Trust", "card_name": "X1234", "cvv": "123"}
    )
    assert r.fields["bank"] == "Deccan XXX Trust"
    assert r.fields["card_name"] == "X1234"  # not a whole-token match


def test_other_types_keep_their_fields_untouched(photo):
    r = _fields_of(photo, "health_policy", {"policy_number": "4111 1111 1111 1111"})
    assert r.fields["policy_number"] == "4111 1111 1111 1111"


@pytest.mark.parametrize(
    "shown",
    [
        "4111  1111  1111  1111",
        "4111.1111.1111.1111",
        "4111/1111/1111/1111",
        "4111 - 1111 - 1111 - 1111",
        "4111" + chr(160) + "1111" + chr(160) + "1111" + chr(160) + "1111",
    ],
)
def test_a_card_name_with_other_separators_is_masked(photo, shown):
    r = _fields_of(photo, "card_front", {"number": _CARD_NUMBER, "card_name": shown})
    name = r.fields["card_name"]
    assert name.count("1") == 4 and name.endswith("1111") and "X" in name


def test_a_letter_or_statement_keeps_dates_and_amounts(photo):
    fill = {"bank": "Deccan", "statement_date": "2026-10-01", "total_due": 12345.5}
    r = _fields_of(photo, "card_statement", {**fill, "card_name": "Period 01/10/2026 - 31/10/2026"})
    assert r.fields["card_name"] == "Period 01/10/2026 - 31/10/2026"
    assert r.fields["total_due"] == "12345.5"
    letter = _fields_of(
        photo, "card_welcome_letter", {"bank": "Deccan", "card_name": "4111.1111.1111.1111"}
    )
    assert letter.fields["card_name"] == "XXXX.XXXX.XXXX.1111"


@pytest.mark.parametrize(
    "shown",
    [
        "4111    1111    1111    1111",
        "4111\t1111\t1111\t1111",
        "\u2013".join(["4111", "1111", "1111", "1111"]),
        "\u2011".join(["4111", "1111", "1111", "1111"]),
        "4111_1111_1111_1111",
        "\u200b".join(["4111", "1111", "1111", "1111"]),
        "4111 . - 1111 . - 1111 . - 1111",
        "ref 411111111111111112345",
    ],
)
def test_a_card_field_holding_thirteen_digits_is_masked(photo, shown):
    r = _fields_of(photo, "card_front", {"number": _CARD_NUMBER, "card_name": shown})
    name = r.fields["card_name"]
    assert sum(c.isdigit() for c in name) <= 4
