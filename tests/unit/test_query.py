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
    PROMPT_READ_V1,
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
            areas=[Area.insurance],
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
        [Area.insurance],
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
    assert messages[0]["content"] == PROMPT_READ_V1 and messages[1]["content"] == "x"
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
