import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from household_vault.doctypes import DocType
from household_vault.filing.records import (
    RECORD_VERSION,
    DocumentRecord,
    build_record,
    decision_from_json,
    decision_to_json,
    read_record,
    record_rows,
    stored_reading,
    write_record,
)
from household_vault.vaultroot import RECORDS
from tests.unit.filing.samples import (
    DECISION,
    ITEM,
    NOW,
    READING,
    card_reading,
    reading_with_box,
)


def test_record_rounds_floats_round_trips_and_holds_no_secret(vault):
    rec = build_record(
        ITEM,
        stored_reading(reading_with_box((0.123456789, 0.2, 0.3, 0.4))),
        DECISION,
        "a/b.pdf",
        None,
        NOW,
    )
    assert rec.linked_people == ["p3"]  # the owner is never also linked
    assert rec.pages[0].lines[0].bbox[0] == 0.1235
    assert rec.pages[0].lines[0].confidence == 0.877
    assert rec.reading.seconds == {"read": 1.2, "fill": 12.3}
    write_record(vault, rec)
    row, people, _ = record_rows(read_record(vault, rec.id))
    assert row.rel_path == "a/b.pdf" and people == [("p1", "owner"), ("p3", "linked")]
    card = card_reading(
        secret_values={"number": "4111111111111111"}, line_text="4111 1111 1111 1111"
    )
    dump = build_record(
        ITEM, stored_reading(card), DECISION, "a.jpg", "uuid", NOW
    ).model_dump_json()
    assert "4111 1111 1111 1111" not in dump and "XXXX XXXX XXXX 1111" in dump
    misread = card_reading(line_text="4111 1111 1111 1112")  # fails Luhn: masked on card items only
    assert "XXXX XXXX XXXX 1112" in json.dumps(stored_reading(misread, card_item=True))


def test_stored_reading_masks_by_type_and_never_dumps_secrets():
    plain = reading_with_box(text="Ref 4111 1111 1111 1112 end")  # a health policy, fails Luhn
    assert "1112 end" in json.dumps(stored_reading(plain))  # other types keep non-card numbers
    assert "XXXX XXXX XXXX 1112" in json.dumps(stored_reading(plain, card_item=True))
    for kind in (DocType.other, None):  # unknown types mask every long run
        unsure = reading_with_box(text="Ref 4111 1111 1111 1112 end", doc_type=kind)
        assert "XXXX XXXX XXXX 1112" in json.dumps(stored_reading(unsure))
    card = card_reading(secret_values={"number": "4111111111111111"})
    assert "4111111111111111" not in json.dumps(stored_reading(card))


def test_the_record_is_a_plain_file_in_the_records_folder(vault):
    rec = build_record(ITEM, stored_reading(READING), DECISION, "a/b.pdf", None, NOW)
    rel = write_record(vault, rec)
    assert rel == f"{RECORDS}/{rec.id}.json" and vault.exists(rel)
    assert read_record(vault, rec.id) == rec
    assert rec.record_version == RECORD_VERSION == 1
    data = json.loads(vault.read_bytes(rel))
    assert data["fields"]["insurer"] == "Star Health" and data["linked_people"] == ["p3"]
    assert (rec.doc_type, rec.owner, rec.area, rec.sha256) == (
        DocType.health_policy,
        "p1",
        "insurance",
        ITEM.sha256,
    )


def test_a_newer_record_version_is_refused(vault):
    rec = build_record(ITEM, stored_reading(READING), DECISION, "a/b.pdf", None, NOW)
    data = json.loads(rec.model_dump_json())
    data["record_version"] = 2
    with pytest.raises(ValidationError):
        DocumentRecord.model_validate(data)


def test_overrides_win_over_the_reading_and_extra_fields_cannot_carry_a_secret():
    item = ITEM.__class__(
        **{
            **ITEM.__dict__,
            "overrides": {"doc_type": "card_front", "fields": {"bank": "SBI"}},
        }
    )
    stored = stored_reading(READING)
    stored["issues"] = {"bank": "unreadable", "number": "bad"}
    rec = build_record(
        item,
        stored,
        DECISION,
        "a/b.jpg",
        "uuid",
        NOW,
        {"last4": "1111", "number": "4111111111111111"},
    )
    assert rec.doc_type is DocType.card_front
    assert rec.fields["bank"] == "SBI" and rec.fields["last4"] == "1111"
    assert rec.fields["number"] is None  # a secret field is never kept
    assert rec.issues == {"number": "bad"}  # the owner's answer clears the issue on that field


def test_floats_in_fields_are_rounded():
    rec = build_record(
        ITEM,
        stored_reading(reading_with_box(fields={"rate": 4.123456789})),
        DECISION,
        "a",
        None,
        NOW,
    )
    assert rec.fields["rate"] == 4.1235


def test_the_owner_is_one_row_and_not_also_linked():
    rec = build_record(ITEM, stored_reading(READING), DECISION, "a/b.pdf", None, NOW)
    _row, people, pages = record_rows(rec)
    assert [p for p, _ in people].count("p1") == 1 and len(pages) == 1
    assert _row.item_id == ITEM.id and _row.created_at == NOW


def test_ids_and_times_can_be_fixed_for_a_rebuild():
    when = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
    a = build_record(ITEM, stored_reading(READING), DECISION, "a", None, when, doc_id="d" * 32)
    b = build_record(ITEM, stored_reading(READING), DECISION, "a", None, when, doc_id="d" * 32)
    assert a == b and a.id == "d" * 32
    assert build_record(ITEM, stored_reading(READING), DECISION, "a", None, when).id != a.id


def test_a_decision_round_trips_as_json():
    assert decision_from_json(json.loads(json.dumps(decision_to_json(DECISION)))) == DECISION


def test_a_record_keeps_a_scrubbed_name_and_the_origin_for_a_rebuild():
    item = ITEM.__class__(
        **{**ITEM.__dict__, "original_name": "Aadhaar 2345 6789 0123 scan.pdf", "origin": "upload"}
    )
    rec = build_record(item, stored_reading(READING), DECISION, "a/b.pdf", None, NOW)
    assert rec.origin == "upload" and rec.original_name == "Aadhaar scan.pdf"
    assert "2345" not in rec.model_dump_json()
    plain = build_record(ITEM, stored_reading(READING), DECISION, "a/b.pdf", None, NOW)
    assert (plain.original_name, plain.origin) == ("policy.pdf", "inbox")


def test_a_name_that_is_all_identifier_still_gives_a_usable_name():
    item = ITEM.__class__(**{**ITEM.__dict__, "original_name": "2345 6789 0123 4567"})
    assert build_record(ITEM, stored_reading(READING), DECISION, "a", None, NOW).original_name
    assert build_record(item, stored_reading(READING), DECISION, "a", None, NOW).original_name


def test_only_schema_fields_and_last4_can_be_added_to_a_record():
    card_item = ITEM.__class__(**{**ITEM.__dict__, "overrides": {"doc_type": "card_front"}})
    for bad in ({"pin": "4321"}, {"password": "x"}):
        with pytest.raises(ValueError, match="not a field"):
            build_record(card_item, stored_reading(card_reading()), DECISION, "a", "u", NOW, bad)
    ok = build_record(
        card_item, stored_reading(card_reading()), DECISION, "a", "u", NOW, {"last4": "1111"}
    )
    assert ok.fields["last4"] == "1111"


def test_a_secret_digit_run_is_hidden_in_lines_and_issues():
    card = card_reading(
        secret_values={"number": "4111111111111111", "cvv": "123"},
        line_text="4111 1111 1111 1111 CVV 123 Main 1234",
    )
    card.issues = {"cvv": "CVV 123 is too short", "number": "read 4111 1111 1111 1112"}
    out = stored_reading(card, card_item=True)
    text = out["pages"][0]["lines"][0]["text"]
    assert text == "XXXX XXXX XXXX 1111 CVV XXX Main XXXX"
    assert out["issues"]["cvv"] == "CVV XXX is too short"
    assert "123" not in json.dumps(out).replace("1234", "")


def _stored_texts(text, fill, type_, photo, *, card_item=False):
    from household_vault.intake.sniff import FileKind
    from household_vault.reading.engines import Engines, VisionPageReader
    from household_vault.reading.pipeline import read_document
    from household_vault.reading.source import DocumentSource
    from tests.fakes import FakeModels, FakeOcr

    models = FakeModels(type_=type_, fill=json.dumps(fill))
    reading = read_document(
        DocumentSource(FileKind.jpeg, data=photo),
        "k" * 64,
        Engines(VisionPageReader(FakeOcr(text=text)), models),
        mode="dev",
    )
    stored = stored_reading(reading, card_item=card_item)
    return [ln["text"] for p in stored["pages"] for ln in p["lines"]]


def test_a_cvv_the_fill_missed_is_masked_in_stored_lines(photo):
    texts = _stored_texts(
        "AUTHORISED SIGNATURE 123 call 1800 22 3344 if found",
        {"bank": "Deccan", "cvv": None},
        "card_front",
        photo,
        card_item=True,
    )
    assert texts[0] == "AUTHORISED SIGNATURE XXX call XXXX 22 XXXX if found"


def test_a_misread_cvv_leaves_nothing_of_the_printed_one(photo):
    texts = _stored_texts(
        "AUTHORISED SIGNATURE 123",
        {"bank": "Deccan", "cvv": "128"},
        "card_front",
        photo,
        card_item=True,
    )
    assert "123" not in texts[0] and "128" not in texts[0]


def test_a_lone_back_typed_other_is_masked_too(photo):
    texts = _stored_texts("AUTHORISED SIGNATURE 123 not transferable", {}, "other", photo)
    assert texts[0] == "AUTHORISED SIGNATURE XXX not transferable"


def test_a_glued_run_of_digits_on_a_card_page_is_masked(photo):
    glued = "4111111111111111123"  # a number and a CVV with no space, then more digits
    texts = _stored_texts(f"NUMBER {glued}9999", {}, "card_front", photo, card_item=True)
    assert "4111" not in texts[0] and texts[0].endswith("9999")


def test_a_masked_number_keeps_its_last_four_and_dates_stay(photo):
    texts = _stored_texts(
        "4111 1111 1111 1111 VALID THRU 08/29 and 08/2029 ref 5678",
        {},
        "card_front",
        photo,
        card_item=True,
    )
    assert texts[0] == "XXXX XXXX XXXX 1111 VALID THRU 08/29 and 08/2029 ref XXXX"


def test_other_types_keep_their_numbers_in_stored_lines(photo):
    texts = _stored_texts(
        "Policy 123456 issued", {"policy_number": "123456"}, "health_policy", photo
    )
    assert texts[0] == "Policy 123456 issued"
