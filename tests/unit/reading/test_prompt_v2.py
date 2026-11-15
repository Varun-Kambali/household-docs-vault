import json

from household_vault.doctypes import LABEL, DocType
from household_vault.reading.prompt import (
    CLASSIFY_SYSTEM,
    OCR_TEXT_LIMIT,
    PROMPT_V1,
    PROMPT_V2,
    classify_prompt,
    classify_schema,
)


def test_the_app_uses_v2_while_spikes_and_finetune_stay_on_v1():
    import finetune.prepare
    import spikes.extraction.prompt as spike

    assert PROMPT_V2.version == "v2" and PROMPT_V2.system.startswith(PROMPT_V1.system)
    assert spike.SYSTEM == finetune.prepare.SYSTEM == PROMPT_V1.system
    assert "Tab, Cap, Syp, Inj" in PROMPT_V2.system
    assert "one item per printed entry" in PROMPT_V2.system


def test_classify_schema_lists_every_type_but_the_recording():
    schema = classify_schema()
    assert schema["required"] == ["doc_type"]
    values = schema["properties"]["doc_type"]["enum"]
    assert set(values) == {t.value for t in DocType} - {"visit_recording"}
    json.dumps(schema)


def test_classify_prompt_labels_types_and_limits_the_text():
    text = classify_prompt("x" * (OCR_TEXT_LIMIT + 500))
    assert f"health_policy: {LABEL[DocType.health_policy]}" in text
    assert "x" * OCR_TEXT_LIMIT in text and "x" * (OCR_TEXT_LIMIT + 1) not in text
    assert CLASSIFY_SYSTEM.startswith("You sort Indian household documents")
