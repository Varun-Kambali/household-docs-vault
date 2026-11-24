import json
from datetime import date

import httpx
import pytest
from pydantic import ValidationError
from vault_synth.household import HOUSEHOLD

from household_vault.doctypes import Area, DocType
from household_vault.reading.ollama import ModelError, ModelUnavailable, OllamaClient
from household_vault.search.dates import DateRange
from household_vault.search.query import (
    PROMPT_READ,
    PROMPT_READ_V1,
    PROMPT_READ_V2,
    DateSlot,
    OllamaPromptReader,
    QueryReading,
    read_prompt,
    resolve,
)
from household_vault.search.vocab import AREA_LABELS, DATE_ROLES, FIELD_LABELS, TYPE_WORDS
from tests.fakes import FakePromptReader

TODAY = date(2026, 11, 21)
VALID = {
    "intent": "find",
    "people": [],
    "types": [],
    "areas": [],
    "field": None,
    "date": None,
    "place": None,
    "words": "x",
}


@pytest.fixture
def household():
    return HOUSEHOLD


def reading(**kw) -> QueryReading:
    return QueryReading(**{**VALID, **kw})


def capture(sent: list[dict], content: str | None = None, status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(status, json={"message": {"content": content or json.dumps(VALID)}})

    return httpx.MockTransport(handler)


def ollama_reader(sent, **kw) -> OllamaPromptReader:
    client = OllamaClient("http://127.0.0.1:11434", transport=capture(sent, **kw))
    return OllamaPromptReader(client, "qwen3:4b")


def test_unread_parts_are_reported_not_guessed(household):  # Review Focus 14
    q = resolve(
        reading(
            intent="list", people=["Anil"], date=DateSlot(role="expiry", phrase="before Diwali")
        ),
        household,
        TODAY,
    )
    assert (q.people, q.range, q.unread) == ([], None, ["person: Anil", "date: before Diwali"])


def test_first_names_aliases_and_everyone(household):
    assert resolve(reading(people=["Ravi"]), household, TODAY).people == ["p1"]
    assert resolve(reading(people=["S N Rao"]), household, TODAY).people == ["p4"]
    assert resolve(reading(people=["everyone"]), household, TODAY).people == []


def test_no_filter_words_and_home(household):
    for word in ("all", "Family", "us", "me", "my", "I"):
        q = resolve(reading(people=[word]), household, TODAY)
        assert (q.people, q.unread) == ([], [])
    assert resolve(reading(people=["house"]), household, TODAY).people == ["home"]
    assert resolve(reading(people=["Home"]), household, TODAY).people == ["home"]


def test_people_are_unique_and_an_ambiguous_name_is_unread(household):
    q = resolve(reading(people=["Ravi", "R K Rao", "Kavita", "Rao"]), household, TODAY)
    assert q.people == ["p1", "p2"]
    assert q.unread == ["person: Rao"]
    assert resolve(reading(people=["K Rao"]), household, TODAY).unread == ["person: K Rao"]


def test_a_possessive_is_dropped(household):
    assert resolve(reading(people=["Kavita's"]), household, TODAY).people == ["p2"]


def test_forward_roles_start_today_when_only_an_end_is_given(household):
    q = resolve(
        reading(intent="list", date=DateSlot(role="expiry", phrase="before March")),
        household,
        TODAY,
    )
    assert q.range == DateRange(start=TODAY, end=date(2027, 2, 28))
    assert q.role == "expiry"


def test_other_roles_and_full_spans_keep_the_range_as_read(household):
    q = resolve(reading(date=DateSlot(role="purchase", phrase="before March")), household, TODAY)
    assert q.range == DateRange(start=None, end=date(2027, 2, 28))
    q = resolve(reading(date=DateSlot(role="due", phrase="next 30 days")), household, TODAY)
    assert q.range == DateRange(start=TODAY, end=date(2026, 12, 21))
    q = resolve(reading(date=DateSlot(role=None, phrase="FY 2025-26")), household, TODAY)
    assert (q.role, q.range) == (None, DateRange(start=date(2025, 4, 1), end=date(2026, 3, 31)))


def test_the_rest_of_the_reading_passes_through(household):
    q = resolve(
        reading(
            intent="lookup",
            types=[DocType.vehicle_policy],
            areas=[Area.property],
            field="policy_number",
            place="Croma",
            words="car",
        ),
        household,
        TODAY,
    )
    assert (q.intent, q.types, q.areas, q.field, q.place, q.words) == (
        "lookup",
        [DocType.vehicle_policy],
        [Area.property],
        "policy_number",
        "Croma",
        "car",
    )
    assert q.unread == [] and q.range is None and q.role is None


def test_the_reading_refuses_a_field_that_is_not_askable():
    with pytest.raises(ValidationError):
        reading(field="password")


def test_the_schema_lists_the_askable_fields_as_an_enum():
    schema = QueryReading.model_json_schema()
    options = schema["properties"]["field"]["anyOf"]
    assert {"type": "string", "enum": list(FIELD_LABELS)} in options
    assert {"type": "null"} in options


def test_broken_model_json_falls_back_to_keywords():
    fake = FakePromptReader({"ravi car policy": "{"})
    q = read_prompt("ravi car policy", fake)
    assert (q.intent, q.words) == ("find", "ravi car policy")
    assert (q.people, q.types, q.areas, q.field, q.date, q.place) == ([], [], [], None, None, None)
    assert fake.calls == 2  # one retry


def test_json_that_fails_the_schema_is_retried_once():
    bad = json.dumps({**VALID, "intent": "delete"})
    fake = FakePromptReader({"p": [bad, json.dumps({**VALID, "words": "ok"})]})
    assert read_prompt("p", fake).words == "ok"
    assert fake.calls == 2 and fake.prompts == ["p", "p"]


def test_valid_json_is_read_with_one_call():
    fake = FakePromptReader({"p": json.dumps({**VALID, "intent": "list", "words": "w"})})
    assert read_prompt("p", fake).intent == "list"
    assert fake.calls == 1


@pytest.mark.parametrize("error", [ModelUnavailable("off"), ModelError("slow")])
def test_a_model_that_is_off_or_failing_raises_model_unavailable(error):
    fake = FakePromptReader({}, fail=error)
    with pytest.raises(ModelUnavailable) as caught:
        read_prompt("secret words", fake)
    assert "secret words" not in str(caught.value)
    assert fake.calls == 1  # no retry


def test_the_reading_call_holds_only_the_prompt_and_the_vocabulary():
    sent: list[dict] = []
    read_prompt("x", ollama_reader(sent))
    body = sent[0]
    messages = body["messages"]
    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[0]["content"] == PROMPT_READ and messages[1]["content"] == "x"
    assert "images" not in messages[1]
    assert body["options"]["num_ctx"] == 4096 and body["options"]["num_predict"] == 400
    assert body["format"] == QueryReading.model_json_schema()
    assert body["model"] == "qwen3:4b"


def test_the_system_text_is_built_from_the_vocabulary():
    for t, words in TYPE_WORDS.items():
        assert t.value in PROMPT_READ_V1 and words[0] in PROMPT_READ_V1
    for area, label in AREA_LABELS.items():
        assert area.value in PROMPT_READ_V1 and label in PROMPT_READ_V1
    for key, label in FIELD_LABELS.items():
        assert key in PROMPT_READ_V1 and label in PROMPT_READ_V1
    roles = {r for per_type in DATE_ROLES.values() for r in per_type}
    assert all(r in PROMPT_READ_V1 for r in roles)
    assert "never work out a date" in PROMPT_READ_V1


def test_the_reader_names_its_model():
    assert ollama_reader([]).name == "ollama:qwen3:4b"


def test_a_range_is_never_inverted(household):
    # an end already past: starting today would invert it
    q = resolve(reading(date=DateSlot(role="expiry", phrase="before March 2024")), household, TODAY)
    assert (q.range, q.unread) == (None, ["date: before March 2024"])
    q = resolve(
        reading(date=DateSlot(role="due", phrase="before 1 January 2026")), household, TODAY
    )
    assert (q.range, q.unread) == (None, ["date: before 1 January 2026"])
    # an end of today is the edge that still reads
    q = resolve(reading(date=DateSlot(role="renewal", phrase="by 21 November")), household, TODAY)
    assert q.range == DateRange(start=TODAY, end=TODAY) and q.unread == []
    # a non-forward role keeps a past end as read: it is not inverted
    q = resolve(
        reading(date=DateSlot(role="purchase", phrase="before March 2024")), household, TODAY
    )
    assert q.range == DateRange(start=None, end=date(2024, 2, 29))


def test_a_listed_type_beats_its_area(household):
    q = resolve(
        reading(
            intent="list",
            types=[DocType.form_16],
            areas=[Area.tax, Area.insurance],
        ),
        household,
        TODAY,
    )
    assert q.types == [DocType.form_16] and q.areas == [Area.insurance]
    both = resolve(reading(types=[DocType.passport], areas=[Area.identity]), household, TODAY)
    assert both.types == [DocType.passport] and both.areas == []
    # a type outside the area leaves the area alone; areas alone are kept
    assert resolve(reading(types=[DocType.passport], areas=[Area.tax]), household, TODAY).areas == [
        Area.tax
    ]
    assert resolve(reading(areas=[Area.tax]), household, TODAY).areas == [Area.tax]


def test_a_role_no_selected_type_has_falls_back_to_the_document_date(household):
    phrase = DateSlot(role="expiry", phrase="this year")
    invoices = resolve(
        reading(intent="list", types=[DocType.tax_invoice], date=phrase), household, TODAY
    )
    assert invoices.role == "document" and invoices.range is not None
    area = resolve(reading(intent="list", areas=[Area.cards], date=phrase), household, TODAY)
    assert area.role == "document"  # no card type has an expiry date role
    policies = resolve(
        reading(intent="list", types=[DocType.health_policy], date=phrase), household, TODAY
    )
    assert policies.role == "expiry"
    anything = resolve(reading(intent="list", date=phrase), household, TODAY)
    assert anything.role == "expiry"  # no type named: the role stays as read
    mixed = resolve(
        reading(intent="list", types=[DocType.tax_invoice, DocType.passport], date=phrase),
        household,
        TODAY,
    )
    assert mixed.role == "expiry"  # one selected type has it


def test_the_current_reading_prompt_is_v2_and_v1_is_kept():
    assert PROMPT_READ is PROMPT_READ_V2 and PROMPT_READ_V1 != PROMPT_READ_V2
    assert "Document types (type: words people use)" in PROMPT_READ_V1


def test_v2_has_a_shorter_vocabulary_and_names_every_type_area_field_and_role_once_in_its_lists():
    vocab_v1 = PROMPT_READ_V1.split("Document types (type: words people use):")[1]
    vocab_v2 = PROMPT_READ_V2.split("Document types by area")[1].split("Examples:")[0]
    assert len(vocab_v2) < len(vocab_v1) * 0.7
    for t in TYPE_WORDS:
        assert t.value in PROMPT_READ_V2
    for area in AREA_LABELS:
        assert f"{area.value}:" in PROMPT_READ_V2
    fields = PROMPT_READ_V2.split("Fields (use the id):")[1].split("\n")[0]
    assert [f.strip() for f in fields.split(",")] == list(FIELD_LABELS)
    for role in {r for per_type in DATE_ROLES.values() for r in per_type}:
        assert f"- {role}:" in PROMPT_READ_V2
    assert "never work out a date" in PROMPT_READ_V2


def test_v2_has_an_intent_guide_and_a_role_guide_with_an_example_each():
    for cue in ("which", "what", "all", "any", "show me", "where is", "open", "is", "when"):
        assert cue in PROMPT_READ_V2
    for intent in ("lookup", "list", "find"):
        assert f"- {intent}:" in PROMPT_READ_V2
    for word in ("expire", "valid till", "renew", "due", "pay by", "bought", "purchased", "issued"):
        assert word in PROMPT_READ_V2
    assert "dated" in PROMPT_READ_V2 and "FY" in PROMPT_READ_V2


# -- the backstop: slots the model left empty, read from the prompt by code ----------------------


def test_a_household_name_in_the_prompt_fills_an_empty_people_slot(household):
    q = resolve(reading(intent="find", types=[DocType.pan]), household, TODAY, "Kavita's PAN")
    assert (q.people, q.backstop_conflicts) == (["p2"], 0)


def test_a_full_name_and_an_alias_are_found_in_the_prompt(household):
    assert resolve(reading(), household, TODAY, "policies of Ravi K Rao").people == ["p1"]
    assert resolve(reading(), household, TODAY, "S N Rao passport").people == ["p4"]


def test_everyone_words_and_home_are_not_names_for_the_backstop(household):
    q = resolve(reading(), household, TODAY, "all my house insurance papers")
    assert q.people == []


def test_the_models_people_win_and_a_different_name_is_counted(household):
    q = resolve(reading(people=["Ravi"]), household, TODAY, "Kavita's PAN")
    assert (q.people, q.backstop_conflicts) == (["p1"], 1)


def test_the_models_people_and_the_prompt_agreeing_is_not_a_conflict(household):
    q = resolve(reading(people=["Kavita"]), household, TODAY, "Kavita's PAN")
    assert (q.people, q.backstop_conflicts) == (["p2"], 0)


def test_a_name_the_household_does_not_hold_is_not_invented_by_the_backstop(household):
    q = resolve(reading(), household, TODAY, "Anil's policy")
    assert (q.people, q.unread) == ([], [])


def test_a_date_phrase_in_the_prompt_fills_an_empty_date_slot(household):
    q = resolve(reading(intent="list"), household, TODAY, "which policies expire before March")
    assert (q.role, q.range) == ("expiry", DateRange(start=TODAY, end=date(2027, 2, 28)))


def test_the_backstop_role_comes_from_a_small_word_map(household):
    def role(prompt: str):
        return resolve(reading(), household, TODAY, prompt).role

    assert role("valid till December") == "expiry"
    assert role("what renews in March") == "renewal"
    assert role("premiums due next month") == "due"
    assert role("bought last year") == "purchase"
    assert role("licences issued in March 2020") == "issue"
    assert role("certificates dated last year") == "document"
    assert role("this year's bills") == "document"


def test_a_date_with_no_role_word_is_the_document_date(household):
    q = resolve(reading(), household, TODAY, "bills for FY 2025-26")
    assert (q.role, q.range) == (
        "document",
        DateRange(start=date(2025, 4, 1), end=date(2026, 3, 31)),
    )


def test_the_word_may_alone_is_not_a_date(household):
    assert resolve(reading(), household, TODAY, "may I see the passport").range is None


def test_the_models_date_wins_and_a_different_span_is_counted(household):
    slot = DateSlot(role="expiry", phrase="before June")
    q = resolve(reading(date=slot), household, TODAY, "expiring before March")
    assert (q.range, q.backstop_conflicts) == (DateRange(start=TODAY, end=date(2027, 5, 31)), 1)


def test_a_prompt_with_no_date_leaves_the_slot_empty(household):
    q = resolve(reading(), household, TODAY, "Ravi's passport number")
    assert (q.role, q.range, q.unread) == (None, None, [])


def test_a_type_word_in_the_prompt_fills_empty_types_and_areas(household):
    q = resolve(reading(), household, TODAY, "when does the passport expire")
    assert q.types == [DocType.passport]


def test_a_type_word_is_not_used_when_the_model_named_an_area_or_a_type(household):
    q = resolve(reading(areas=[Area.insurance]), household, TODAY, "my passport")
    assert (q.types, q.areas, q.backstop_conflicts) == ([], [Area.insurance], 1)
    q = resolve(reading(types=[DocType.pan]), household, TODAY, "my passport")
    assert (q.types, q.backstop_conflicts) == ([DocType.pan], 1)


def test_a_type_word_must_be_a_whole_word(household):
    assert resolve(reading(), household, TODAY, "passportz and more").types == []
    assert resolve(reading(), household, TODAY, "the mediclaim policy").types == [
        DocType.health_policy
    ]


def test_without_a_prompt_there_is_no_backstop(household):
    q = resolve(reading(), household, TODAY)
    assert (q.people, q.types, q.range, q.backstop_conflicts) == ([], [], None, 0)


def test_a_plural_type_word_counts(household):
    assert resolve(reading(), household, TODAY, "invoices from this year").types == [
        DocType.tax_invoice
    ]
    assert resolve(reading(), household, TODAY, "my payslips").types == [DocType.payslip]


def test_a_date_the_model_wrote_that_code_cannot_read_is_read_from_the_prompt(household):
    slot = DateSlot(role="expiry", phrase="expiring before January 2027")
    q = resolve(
        reading(date=slot),
        household,
        TODAY,
        "expiring before January 2027",
    )
    assert (q.range, q.unread, q.backstop_conflicts) == (
        DateRange(start=TODAY, end=date(2026, 12, 31)),
        [],
        0,
    )
    slot = DateSlot(role="expiry", phrase="in the next 6 months")
    q = resolve(reading(date=slot), household, TODAY, "what expires in the next 6 months")
    assert q.range == DateRange(start=TODAY, end=date(2027, 5, 21))


def test_a_date_neither_the_model_nor_the_prompt_can_read_stays_unread(household):
    slot = DateSlot(role="expiry", phrase="before Diwali")
    q = resolve(reading(date=slot), household, TODAY, "expiring before Diwali")
    assert (q.range, q.unread) == (None, ["date: before Diwali"])


def test_a_second_readable_date_does_not_replace_the_unreadable_phrase(household):
    slot = DateSlot(role="expiry", phrase="before Diwali")
    q = resolve(
        reading(intent="list", date=slot),
        household,
        TODAY,
        "Croma bills from March expiring before Diwali",
    )
    assert (q.range, q.unread) == (None, ["date: before Diwali"])


def test_the_role_cue_nearest_the_date_phrase_gives_the_role(household):
    q = resolve(reading(), household, TODAY, "expiring policies bought last year")
    assert q.role == "purchase"
    q = resolve(reading(), household, TODAY, "policies expiring before March, bought last year")
    assert q.role == "expiry"


def test_a_type_word_narrows_the_models_area_when_it_holds_that_type(household):
    q = resolve(reading(areas=[Area.tax]), household, TODAY, "Form 16s for this year")
    assert (q.types, q.areas, q.backstop_conflicts) == ([DocType.form_16], [], 0)
    q = resolve(reading(areas=[Area.insurance]), household, TODAY, "Form 16s for this year")
    assert (q.types, q.areas, q.backstop_conflicts) == ([], [Area.insurance], 1)


@pytest.mark.parametrize(
    ("prompt", "place", "types"),
    [
        ("documents from Epic Electronics", "Epic Electronics", []),
        ("papers from DL Motors", "DL Motors", []),
        ("Pan Asia Traders invoices", "Pan Asia Traders", [DocType.tax_invoice]),
        ("Degree College fee receipts", "Degree College", [DocType.tax_invoice]),
        (
            "Vijaya Digital World Sony warranty card",
            "Vijaya Digital World",
            [DocType.warranty_card],
        ),
    ],
)
def test_a_type_word_inside_the_models_place_is_not_a_type(household, prompt, place, types):
    q = resolve(reading(place=place), household, TODAY, prompt)
    assert q.types == types


def test_a_type_word_inside_the_models_words_is_not_a_type(household):
    q = resolve(reading(words="Epic"), household, TODAY, "Epic bills")
    assert q.types == [DocType.tax_invoice]


def test_a_warranty_card_is_a_warranty_card_and_not_also_a_card(household):
    for prompt in ("Sony warranty card", "the guarantee card", "service card for the TV"):
        assert DocType.card_front not in resolve(reading(), household, TODAY, prompt).types
    assert resolve(reading(), household, TODAY, "Sony warranty card").types == [
        DocType.warranty_card
    ]
    assert resolve(reading(), household, TODAY, "my PAN card").types == [DocType.pan]
    assert resolve(reading(), household, TODAY, "my credit card").types == [DocType.card_front]
    assert resolve(reading(), household, TODAY, "my card").types == [DocType.card_front]


def test_a_household_first_name_inside_the_models_place_is_not_a_person(household):
    q = resolve(reading(place="Kiran Electronics"), household, TODAY, "Kiran Electronics bills")
    assert q.people == []


def test_plurals_are_made_per_word(household):
    q = resolve(reading(), household, TODAY, "Kavita warranties")
    assert (q.people, q.types) == (["p2"], [DocType.warranty_card])
    got = resolve(reading(), household, TODAY, "licences and receipts").types
    assert set(got) == {DocType.driving_licence, DocType.tax_invoice}


def test_a_short_code_is_never_pluralised(household):
    for prompt in ("pans", "rcs", "ecs", "dls"):
        assert resolve(reading(), household, TODAY, prompt).types == []
