"""Hand-made prompts that probe the list-intent backstop in `resolve`.

None comes from the val or test sets. Each row gives the prompt, the intent a small model might
read, the slots it might fill, and the intent that must come out."""

from datetime import date

import pytest
from vault_synth.household import HOUSEHOLD

from household_vault.search.query import DateSlot, QueryReading, resolve

TODAY = date(2026, 11, 21)
PLACES = ["Croma", "Nilgiri Bank", "Life Insurance Corporation", "Sony Centre"]
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

EXPIRY = {"field": "expiry_date"}
INSURANCE = {"areas": ["insurance"]}


def _slot(phrase: str, role: str = "expiry") -> dict:
    return {"date": DateSlot(role=role, phrase=phrase)}


# (prompt, model intent, model slots, expected intent)
KEPT = [
    ("Kavita's warranty card", "find", {}, "find"),
    ("the fridge bill", "find", {}, "find"),
    ("Is the AC still under warranty?", "lookup", {}, "lookup"),
    ("Which bank issued Ravi's card?", "lookup", {}, "lookup"),
    ("Which insurer covers Kavita's car?", "lookup", {}, "lookup"),
    ("Which policy did Suresh buy last year?", "lookup", {}, "lookup"),
    ("Which airline did Ravi's ticket use?", "lookup", {}, "lookup"),
    ("Which one expires first?", "lookup", {}, "lookup"),
    ("When does the car insurance expire?", "lookup", EXPIRY, "lookup"),
    ("When does Ravi's passport expire?", "lookup", EXPIRY, "lookup"),
    ("Ravi's passport valid till 2030", "lookup", {**EXPIRY, **_slot("till 2030")}, "lookup"),
    ("the dogs vaccination card", "find", {}, "find"),
    ("fines on the car", "find", {}, "find"),
    ("fines", "find", {}, "find"),
    ("the paper from the school", "find", {}, "find"),
    ("Ravi paper", "find", {}, "find"),
    ("Ravi's record", "find", {}, "find"),
    ("recording of Ravi's visit", "find", {}, "find"),
    ("recorded warranty", "find", {}, "find"),
    ("Ravi's lists", "find", {}, "find"),
    ("Ravi's passport file", "find", {}, "find"),
    ("Croma invoice", "find", {}, "find"),
    ("Kavita's latest bill", "find", {}, "find"),
    # a question about one thing: Important 1 (which/what plus an auxiliary)
    ("Which is Kiran's school?", "lookup", {}, "lookup"),
    ("Which was the last bill from Croma?", "lookup", {}, "lookup"),
    ("Which has the longer warranty, the TV or the fridge?", "lookup", {}, "lookup"),
    ("Which does Ravi use for health cover?", "lookup", {}, "lookup"),
    # Important 2: all, any, every and "What are" inside a question about one thing
    ("Is all of Suresh's insurance paid?", "lookup", {}, "lookup"),
    ("Is all of Suresh's insurance paid?", "find", {}, "find"),
    ("Is every policy renewed?", "lookup", {}, "lookup"),
    ("Has Kavita got all her vaccination records?", "lookup", {}, "lookup"),
    ("Is there any insurance on the scooter?", "lookup", {}, "lookup"),
    ("Do we have any warranty for the AC?", "lookup", {}, "lookup"),
    ("Does Suresh have any warranty on the laptop?", "lookup", {}, "lookup"),
    ("Does Suresh have any warranty on the laptop?", "find", {}, "find"),
    ("What are the terms on Ravi's mediclaim?", "lookup", {}, "lookup"),
    ("What are Suresh's passport details?", "lookup", {}, "lookup"),
    ("What are Ravi's passport details?", "lookup", {}, "lookup"),
    ("What are my options for renewal", "find", {}, "find"),
    ("Ravi's car, all details", "lookup", {}, "lookup"),
    # Important 3: L3 never overrides an asked field or a field label
    (
        "Ravi passport expiry date next year",
        "lookup",
        {**EXPIRY, "types": ["passport"], **_slot("next year")},
        "lookup",
    ),
    (
        "Ravi passport expiry date next year",
        "lookup",
        {"types": ["passport"], **_slot("next year")},
        "lookup",
    ),
    (
        "Croma bill amount October",
        "lookup",
        {"areas": ["purchases"], "place": "Croma", **_slot("October", "purchase")},
        "lookup",
    ),
    # a possessive plural means many documents, which is the design
    ("Kavita's bills", "find", {}, "list"),
    ("Ravi's receipts", "find", {}, "list"),
    ("Kiran's certificates", "find", {}, "list"),
    ("Ravi's docs", "find", {}, "list"),
    ("Ravi's records", "find", {}, "list"),
    ("Kavita's insurance papers", "find", {}, "list"),
    # stay lists as specified (L3 with no field and no field label)
    (
        "Ravi passport renewal due next March",
        "lookup",
        {"types": ["passport"], **_slot("next March", "renewal")},
        "list",
    ),
    (
        "Kavita car insurance expiring December",
        "lookup",
        {"areas": ["insurance"], **_slot("December")},
        "list",
    ),
]

LISTS = [
    ("all of Ravi's documents", "find", {}),
    ("list Kavita's bills", "find", {}),
    ("every warranty we have", "lookup", {}),
    ("What do we have from Croma?", "lookup", {"place": "Croma"}),
    ("Kiran's school receipts", "find", {}),
    ("papers for the car", "find", {}),
    ("Which documents are from Nilgiri Bank?", "find", {"place": "Nilgiri Bank"}),
    ("all the files for Suresh", "find", {}),
    ("Ravi vehicle documents", "find", {}),
    ("medical records of Kiran", "find", {}),
    ("Ravi's bills from Croma", "find", {"place": "Croma"}),
    ("Ravi renewals", "lookup", {"field": "expiry_date"}),
    # Minor 4: the plural of a generic word is a list cue
    ("Suresh's insurance policies", "find", INSURANCE),
    # Minor 1: a plural type word with a date field and no question
    ("Kavita invoices", "lookup", {"field": "purchase_date"}),
    ("Kavita warranties", "lookup", {"field": "expiry_date"}),
    # What are, with a plural thing after it
    ("What are Suresh's policies?", "lookup", {}),
]

KNOWN_LIMITS = [
    pytest.param(
        "filles for Ravi",
        "find",
        {},
        marks=pytest.mark.xfail(reason="known limit: a cue word under six letters never fuzzes"),
    ),
    pytest.param(
        "listing of Ravi's policies",
        "find",
        {},
        marks=pytest.mark.xfail(reason="known limit: 'listing' is not a cue word"),
    ),
]


def _intent(prompt: str, model_intent: str, slots: dict) -> str:
    reading = QueryReading(**{**VALID, "intent": model_intent, **slots})
    return resolve(reading, HOUSEHOLD, TODAY, prompt, places=PLACES).intent


@pytest.mark.parametrize("prompt, model_intent, slots, expected", KEPT)
def test_the_intent_a_prompt_keeps_or_gets(prompt, model_intent, slots, expected):
    assert _intent(prompt, model_intent, slots) == expected


@pytest.mark.parametrize("prompt, model_intent, slots", LISTS)
def test_prompts_for_many_documents_become_lists(prompt, model_intent, slots):
    assert _intent(prompt, model_intent, slots) == "list"


@pytest.mark.parametrize("prompt, model_intent, slots", KNOWN_LIMITS)
def test_known_limits(prompt, model_intent, slots):
    assert _intent(prompt, model_intent, slots) == "list"
