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
    q = resolve(
        reading(intent="list", areas=[Area.tax]), household, TODAY, "Form 16s for this year"
    )
    assert (q.types, q.areas, q.backstop_conflicts) == ([DocType.form_16], [], 0)
    q = resolve(
        reading(intent="list", areas=[Area.insurance]), household, TODAY, "Form 16s for this year"
    )
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
    assert (q.people, set(q.types)) == (["p2"], {DocType.warranty_card, DocType.extended_warranty})
    got = resolve(reading(), household, TODAY, "licences and receipts").types
    assert set(got) == {DocType.driving_licence, DocType.tax_invoice}


def test_a_short_code_is_never_pluralised(household):
    for prompt in ("pans", "rcs", "ecs", "dls"):
        assert resolve(reading(), household, TODAY, prompt).types == []


# -- the model's people slot holds a household name inside a longer phrase -----------------------


def test_a_household_name_inside_a_longer_phrase_is_that_person_and_the_rest_a_place(household):
    q = resolve(
        reading(people=["Suresh City Electronics Mart"]),
        household,
        TODAY,
        places=["City Electronics Mart"],
    )
    assert (q.people, q.unread, q.place) == (["p4"], [], "City Electronics Mart")
    assert q.backstop_conflicts == 1


def test_the_rest_of_the_phrase_goes_to_words_when_the_place_is_filled(household):
    q = resolve(
        reading(people=["Suresh Sangeetha"], place="Sangeetha Mobiles", words="phone"),
        household,
        TODAY,
        places=["Sangeetha Mobiles"],
    )
    assert (q.people, q.unread, q.place, q.words) == (
        ["p4"],
        [],
        "Sangeetha Mobiles",
        "phone Sangeetha",
    )


def test_a_longer_phrase_without_a_household_name_stays_unread(household):
    q = resolve(reading(people=["Anil Electronics Mart"]), household, TODAY)
    assert (q.people, q.unread, q.place) == ([], ["person: Anil Electronics Mart"], None)


def test_a_name_only_part_of_a_word_is_not_a_household_name(household):
    q = resolve(reading(people=["Sureshwar Traders"]), household, TODAY)
    assert (q.people, q.unread) == ([], ["person: Sureshwar Traders"])


# -- articles and stray words in the people slot -------------------------------------------------


def test_a_leading_article_is_stripped_before_a_person_is_looked_up(household):
    assert resolve(reading(people=["the Kavita"]), household, TODAY).people == ["p2"]
    assert resolve(reading(people=["our Suresh"]), household, TODAY).people == ["p4"]


def test_a_phrase_left_empty_after_stripping_is_dropped_not_unread(household):
    for phrase in ("the", "a", "an", "our", "The"):
        q = resolve(reading(people=[phrase]), household, TODAY)
        assert (q.people, q.unread) == ([], []), phrase


def test_the_unread_name_is_shown_without_its_article(household):
    q = resolve(reading(people=["the Anil"]), household, TODAY)
    assert q.unread == ["person: Anil"]


def test_my_alone_still_means_everyone(household):
    q = resolve(reading(people=["my"]), household, TODAY)
    assert (q.people, q.unread) == ([], [])


# -- a person phrase that is really a stored place -----------------------------------------------

PLACES = ["Kaveri Systems Pvt Ltd", "Anil Diagnostics", "Epic Electronics", "Croma"]


def test_a_phrase_inside_a_stored_place_moves_to_place_and_is_not_unread(household):
    q = resolve(reading(people=["Kaveri Systems"]), household, TODAY, places=PLACES)
    assert (q.people, q.unread, q.place) == ([], [], "Kaveri Systems")


def test_a_stored_place_that_holds_a_household_name_is_still_a_place(household):
    q = resolve(
        reading(people=["Suresh Sangeetha"]),
        household,
        TODAY,
        places=["Suresh Sangeetha Mobiles"],
    )
    assert (q.people, q.unread, q.place) == ([], [], "Suresh Sangeetha")


def test_a_person_phrase_that_is_a_stored_place_goes_to_words_when_place_is_filled(household):
    q = resolve(
        reading(people=["the Kaveri Systems"], place="Croma"), household, TODAY, places=PLACES
    )
    assert (q.unread, q.place, q.words) == ([], "Croma", "x Kaveri Systems")


def test_a_lone_word_of_a_stored_place_stays_unread_as_a_possessive_but_a_whole_value_moves(
    household,
):
    places = [*PLACES, "Anil Diagnostics"]
    possessive = resolve(
        reading(people=["Anil"]), household, TODAY, "Anil's documents", places=places
    )
    assert possessive.unread == ["person: Anil"]
    q = resolve(reading(people=["Anil Diagnostics"]), household, TODAY, places=places)
    assert (q.unread, q.place) == ([], "Anil Diagnostics")
    q = resolve(reading(people=["Croma"]), household, TODAY, places=places)
    assert (q.unread, q.place) == ([], "Croma")


def test_a_place_never_matches_part_of_a_word(household):
    q = resolve(reading(people=["Epic Electron"]), household, TODAY, places=PLACES)
    assert q.unread == ["person: Epic Electron"]


def test_no_places_means_the_old_behaviour(household):
    q = resolve(reading(people=["Kaveri Systems"]), household, TODAY)
    assert q.unread == ["person: Kaveri Systems"]


def test_the_scanners_skip_a_stored_place_found_in_the_prompt_with_the_place_empty(household):
    prompt = "documents from Epic Electronics"
    q = resolve(reading(), household, TODAY, prompt, places=PLACES)
    assert q.types == []
    q = resolve(reading(), household, TODAY, prompt)  # without the stored places it reads voter id
    assert q.types != []


def test_the_scanners_skip_a_stored_place_found_in_the_prompt_with_a_wrong_place(household):
    prompt = "documents from Epic Electronics"
    q = resolve(reading(place="Croma"), household, TODAY, prompt, places=PLACES)
    assert q.types == []


def test_the_people_scan_skips_a_stored_place_found_in_the_prompt(household):
    places = ["Suresh Sangeetha Mobiles"]
    prompt = "invoice from Suresh Sangeetha Mobiles"
    assert resolve(reading(), household, TODAY, prompt, places=places).people == []
    assert resolve(reading(), household, TODAY, prompt).people == ["p4"]


# -- a brand word in the people slot (fix round 3, I1) -------------------------------------------

INSURER = "Tungabhadra Insurance Company Limited"
BRANDS = {
    INSURER: {DocType.gadget_policy, DocType.life_policy},
    "Anil Diagnostics": {DocType.lab_report},
    "Suresh Sangeetha Mobiles": {DocType.tax_invoice},
}


def test_a_brand_word_of_a_stored_insurer_moves_to_place_when_the_query_names_its_type(household):
    prompt = "What is the sum insured on the Tungabhadra gadget insurance policy?"
    q = resolve(reading(people=["the Tungabhadra"]), household, TODAY, prompt, places=BRANDS)
    assert (q.people, q.unread, q.place) == ([], [], "Tungabhadra")
    assert q.types == [DocType.gadget_policy]


def test_a_brand_with_type_words_moves_to_place(household):
    prompt = "next premium due on the Tungabhadra life insurance policy"
    q = resolve(
        reading(people=["Tungabhadra life insurance policy"]),
        household,
        TODAY,
        prompt,
        places=BRANDS,
    )
    assert (q.people, q.unread, q.place) == ([], [], "Tungabhadra")


def test_a_brand_word_with_no_type_named_moves_to_place_unless_possessive(household):
    prompt = "Tungabhadra policy expiry"
    q = resolve(reading(people=["Tungabhadra"]), household, TODAY, prompt, places=BRANDS)
    assert (q.unread, q.place) == ([], "Tungabhadra")
    prompt = "Tungabhadra's documents"
    q = resolve(reading(people=["Tungabhadra"]), household, TODAY, prompt, places=BRANDS)
    assert q.unread == ["person: Tungabhadra"]


def test_a_brand_word_stored_only_on_other_types_stays_unread(household):
    prompt = "Anil life insurance policy"
    q = resolve(reading(people=["Anil"]), household, TODAY, prompt, places=BRANDS)
    assert (q.unread, q.place) == (["person: Anil"], None)
    prompt = "Anil's documents"
    q = resolve(reading(people=["Anil"]), household, TODAY, prompt, places=BRANDS)
    assert q.unread == ["person: Anil"]


def test_a_brand_word_with_a_matching_type_is_a_place(household):
    prompt = "Anil Diagnostics reports"
    q = resolve(reading(people=["Anil Diagnostics"]), household, TODAY, prompt, places=BRANDS)
    assert (q.unread, q.place) == ([], "Anil Diagnostics")
    prompt = "Anil lab report"
    q = resolve(
        reading(people=["Anil"], types=[DocType.lab_report]),
        household,
        TODAY,
        prompt,
        places=BRANDS,
    )
    assert (q.unread, q.place) == ([], "Anil")


# -- an outsider's surname after a household name (fix round 3, Minor 3) -------------------------


def test_a_household_name_with_an_outsiders_surname_stays_unread(household):
    prompt = "Suresh Kumar's PAN number"
    q = resolve(reading(people=["Suresh Kumar"]), household, TODAY, prompt, places=BRANDS)
    assert (q.people, q.unread) == ([], ["person: Suresh Kumar"])


def test_a_household_name_plus_a_stored_place_still_reads_both(household):
    places = {"City Electronics Mart": {DocType.warranty_card}}
    q = resolve(
        reading(people=["Suresh City Electronics Mart"]),
        household,
        TODAY,
        "Suresh City Electronics Mart warranty card brand",
        places=places,
    )
    assert (q.people, q.unread, q.place) == (["p4"], [], "City Electronics Mart")
    q = resolve(
        reading(people=["Suresh Sangeetha Mobiles"]),
        household,
        TODAY,
        "Suresh Sangeetha Mobiles invoice model",
        places={"Sangeetha Mobiles": {DocType.tax_invoice}},
    )
    assert (q.people, q.unread, q.place) == (["p4"], [], "Sangeetha Mobiles")


# -- a stored place that holds type words stays whole (Task 31c) ---------------------------------


def test_a_stored_place_with_type_words_is_not_cut_down(household):
    places = {"Life Insurance Corporation": {DocType.life_policy}}
    q = resolve(
        reading(people=["Life Insurance Corporation"]),
        household,
        TODAY,
        "Life Insurance Corporation policy number",
        places=places,
    )
    assert (q.people, q.unread, q.place) == ([], [], "Life Insurance Corporation")


def test_generic_words_live_in_the_vocabulary():
    from household_vault.search import vocab

    assert "policy" in vocab.GENERIC_WORDS and "documents" in vocab.GENERIC_WORDS


# -- an intent backstop from closed list cues (Task 31c, L1) -------------------------------------


@pytest.mark.parametrize(
    "prompt, model_intent, extra",
    [
        ("documents Orchard Labs", "find", {"place": "Orchard Labs"}),
        ("What do we have from Hill Park Medical?", "lookup", {"place": "Hill Park Medical"}),
        ("docuents Nilgiri Bank", "find", {"place": "Nilgiri Bank"}),
        ("Kavita warranties", "lookup", {"people": ["Kavita"]}),
        ("everything from Croma", "find", {"place": "Croma"}),
        ("all papers for Ravi", "find", {"people": ["Ravi"]}),
        ("which bills came from Croma", "find", {"place": "Croma"}),
    ],
)
def test_a_list_cue_with_no_find_cue_makes_the_intent_a_list(
    household, prompt, model_intent, extra
):
    q = resolve(reading(intent=model_intent, **extra), household, TODAY, prompt)
    assert q.intent == "list"
    assert q.backstop_conflicts >= 1


@pytest.mark.parametrize(
    "prompt, intent, extra",
    [
        ("Show me the documents for Kavita's car", "find", {}),
        ("find the papers from Croma", "find", {}),
        ("open all the files", "find", {}),
        ("where is the document for the fridge", "find", {}),
        ("When does Kavita's car insurance expire?", "lookup", {"field": "expiry_date"}),
        ("What are the documents number on Ravi's PAN", "lookup", {"field": "number"}),
        ("Kavita's warranty card", "find", {}),
        ("Sony TV warranty", "find", {}),
        ("Suresh vehicle service record", "find", {}),
        ("Which shop issued the Nimbus television contract?", "lookup", {}),
    ],
)
def test_a_find_cue_a_field_or_a_singular_keeps_the_models_intent(household, prompt, intent, extra):
    q = resolve(reading(intent=intent, **extra), household, TODAY, prompt)
    assert q.intent == intent


# -- a plural type or role word as the whole object (Task 31c, L2) -------------------------------


def test_a_plural_role_noun_that_names_an_area_makes_a_list_of_that_area(household):
    q = resolve(
        reading(intent="lookup", people=["Suresh"], field="purchase_date", words="purchases"),
        household,
        TODAY,
        "Suresh purchases",
    )
    assert (q.intent, q.field, q.people, q.types, q.areas) == (
        "list",
        None,
        ["p4"],
        [],
        [Area.purchases],
    )


def test_a_plural_role_noun_with_no_area_sets_the_role_and_leaves_types_open(household):
    q = resolve(
        reading(intent="lookup", people=["Kavita"], field="expiry_date"),
        household,
        TODAY,
        "Kavita expiries",
    )
    assert (q.intent, q.field, q.role, q.types, q.areas) == ("list", None, "expiry", [], [])


def test_the_plural_of_warranty_means_every_kind_of_warranty(household):
    q = resolve(
        reading(intent="lookup", people=["Kavita"], types=[DocType.warranty_card]),
        household,
        TODAY,
        "Kavita warranties",
    )
    assert q.intent == "list"
    assert set(q.types) == {DocType.warranty_card, DocType.extended_warranty}


@pytest.mark.parametrize(
    "prompt, field",
    [
        ("When was Suresh's purchase?", "purchase_date"),
        ("What is the purchase date of Suresh's purchases?", "purchase_date"),
        ("Suresh purchase date", "purchase_date"),
        ("Kavita's warranty", None),
    ],
)
def test_a_question_word_a_singular_or_an_asked_value_keeps_a_lookup(household, prompt, field):
    q = resolve(reading(intent="lookup", people=["Suresh"], field=field), household, TODAY, prompt)
    assert q.intent == "lookup"


# -- a date range after a type word, with no question (Task 31c, L3) -----------------------------


def test_a_date_range_after_a_type_word_with_no_question_makes_a_list(household):
    q = resolve(
        reading(
            intent="lookup",
            people=["Suresh"],
            types=[DocType.life_policy],
            date=DateSlot(role="expiry", phrase="by December"),
        ),
        household,
        TODAY,
        "Suresh insurance expiring by December",
    )
    assert (q.intent, q.field) == ("list", None)
    assert q.range is not None
    # only the group word "insurance" is written: the model's single type is a guess
    assert (q.types, q.areas) == ([], [Area.insurance])


def test_a_named_type_stays_when_a_date_range_makes_a_list(household):
    q = resolve(
        reading(
            intent="lookup",
            people=["Suresh"],
            types=[DocType.health_policy],
            date=DateSlot(role="expiry", phrase="by December"),
        ),
        household,
        TODAY,
        "Suresh mediclaim expiring by December",
    )
    assert (q.intent, q.types, q.areas) == ("list", [DocType.health_policy], [])


@pytest.mark.parametrize(
    "prompt",
    [
        "When does Suresh's life insurance expire by December?",
        "What is the expiry of Suresh's life insurance this year?",
        "Is Suresh's life insurance valid till December?",
    ],
)
def test_a_question_word_keeps_a_lookup_with_a_date(household, prompt):
    q = resolve(
        reading(
            intent="lookup",
            people=["Suresh"],
            types=[DocType.life_policy],
            field="expiry_date",
            date=DateSlot(role="expiry", phrase="by December"),
        ),
        household,
        TODAY,
        prompt,
    )
    assert q.intent == "lookup"
