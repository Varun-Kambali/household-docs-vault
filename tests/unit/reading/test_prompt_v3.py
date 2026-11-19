import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from vault_synth.sets import load_set

from household_vault.doctypes import DocType
from household_vault.reading.prompt import (
    CLASSIFY_GUIDE,
    PROMPT_V1,
    PROMPT_V2,
    PROMPT_V3,
    classify_prompt,
    schema_for_prompt,
    schema_json,
)
from household_vault.schemas import SCHEMAS
from household_vault.schemas._coerce import field_kind, parse_amount, parse_date
from household_vault.schemas.parse import parse_json_fields

EVAL_V1 = Path(__file__).resolve().parents[3] / "evals" / "datasets" / "eval-v1"


def test_v3_is_new_and_v1_v2_are_untouched():
    assert PROMPT_V3.version == "v3"
    assert PROMPT_V1.version == "v1" and PROMPT_V2.version == "v2"
    assert PROMPT_V2.system.startswith(PROMPT_V1.system)
    assert "YYYY-MM-DD" in PROMPT_V1.system and "YYYY-MM-DD" in PROMPT_V2.system


def test_v3_says_copy_dates_amounts_and_names_as_printed():
    text = PROMPT_V3.system
    assert "YYYY-MM-DD" not in text and "plain numbers" not in text
    assert "date exactly as printed" in text and "never reorder, convert or drop separators" in text
    assert "20/09/2026" in text and "20 Sep 2026" in text
    assert "amount exactly as printed" in text and "Rs. 10,00,000" in text and "20%" in text
    assert "letter for letter" in text and "never correct, complete or shorten" in text
    assert "If a field is not printed, use null" in text and "Never guess or invent" in text
    assert "Tab, Cap, Syp, Inj" in text and "one item per printed entry" in text


def test_v3_schema_asks_for_dates_and_amounts_as_printed():
    props = schema_for_prompt(SCHEMAS[DocType.health_policy], as_printed=True)["properties"]
    assert props["start_date"] == {
        "type": ["string", "null"],
        "description": "a date, exactly as printed",
    }
    assert props["sum_insured"] == {
        "type": ["string", "null"],
        "description": "an amount exactly as printed",
    }
    assert props["premium"]["type"] == ["string", "null"]
    json.dumps(props)


def test_the_default_schema_stays_the_v1_one_for_spikes_and_finetune():
    props = schema_for_prompt(SCHEMAS[DocType.health_policy])["properties"]
    assert props["start_date"]["description"] == "YYYY-MM-DD"
    assert props["sum_insured"]["type"] == ["number", "null"]
    assert schema_json(SCHEMAS[DocType.health_policy]) == json.dumps(
        schema_for_prompt(SCHEMAS[DocType.health_policy]), ensure_ascii=False
    )


def test_field_descriptions_reach_the_prompt_schema():
    inv = schema_for_prompt(SCHEMAS[DocType.tax_invoice], as_printed=True)["properties"]
    assert inv["seller_location"]["description"] == "the city only, as printed"
    marriage = schema_for_prompt(SCHEMAS[DocType.marriage_certificate], as_printed=True)
    assert marriage["properties"]["parties"]["description"] == (
        "both people the certificate names as married, one entry each"
    )
    rx = schema_for_prompt(SCHEMAS[DocType.prescription], as_printed=True)
    med = rx["properties"]["medicines"]["items"]["properties"]
    assert med["name"]["description"] == "the medicine name only, without its strength"
    assert med["dose"]["description"] == "the strength as printed, for example 500 mg or 60000 IU"
    assert med["timing"]["description"] == "the dosing pattern as printed, for example 1-0-1"


def test_the_type_call_carries_the_guide():
    text = classify_prompt("page text")
    assert CLASSIFY_GUIDE in text
    for phrase in (
        "investment declaration",
        "80C or 80D",
        "ultrasound or scan images",
        "radiologist's written report",
        "not a lab test",
        "bank's letter about a new card",
        "not the card itself",
        "lists medicines a doctor prescribed",
        "lists charges",
    ):
        assert phrase in text, phrase
    assert len(CLASSIFY_GUIDE.split()) < 120


def test_a_fill_answer_as_printed_parses_through_the_code():
    answer = json.dumps(
        {"sum_insured": "Rs. 10,00,000", "start_date": "10/07/2026", "premium": "28,910"}
    )
    parsed = parse_json_fields(SCHEMAS[DocType.health_policy], answer, mode="dev")
    assert parsed.issues == {}
    assert parsed.model.sum_insured == Decimal(1000000)  # type: ignore[attr-defined]
    assert parsed.model.start_date == date(2026, 7, 10)  # type: ignore[attr-defined]
    assert parsed.model.premium == Decimal(28910)  # type: ignore[attr-defined]


def test_every_printed_date_and_amount_in_train_and_val_parses_to_the_truth():
    checked = {"date": 0, "amount": 0}
    for doc in load_set(EVAL_V1):
        if doc.split == "test" or doc.doc_type not in SCHEMAS:
            continue
        schema = SCHEMAS[doc.doc_type]
        for name, text in doc.printed.items():
            if name not in schema.model_fields:
                continue
            kind = field_kind(schema, name)
            truth = doc.fields.get(name)
            if kind == "date":
                assert parse_date(text).isoformat() == truth, (doc.doc_id, name, text)
            elif kind == "amount":
                assert parse_amount(text) == Decimal(str(truth)), (doc.doc_id, name, text)
            else:
                continue
            checked[kind] += 1
    assert checked["date"] > 200 and checked["amount"] > 50
