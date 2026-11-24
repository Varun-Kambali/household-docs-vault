"""A person's prompt, read into a structured query.

A small local model copies the words of the prompt into slots (people, types, field, date and
place phrases). Code then works out who the people are and what the dates mean, and reports
anything it could not read. The model sees only the prompt and the fixed vocabulary, never a
document, and never works out a date.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal, Protocol

from pydantic import AfterValidator, BaseModel, ConfigDict, ValidationError, WithJsonSchema

from household_vault.doctypes import AREA, Area, DocType
from household_vault.people import Household, match_person, normalise_name
from household_vault.reading.engines import prefill_for
from household_vault.reading.ollama import ModelError, ModelUnavailable, OllamaClient
from household_vault.search.dates import DateRange, parse_date_phrase
from household_vault.search.vocab import (
    AREA_LABELS,
    DATE_ROLES,
    FIELD_LABELS,
    TYPE_WORDS,
    DateRole,
)


def _askable(value: str) -> str:
    if value not in FIELD_LABELS:
        raise ValueError("not a field a question can ask for")
    return value


# A plain string checked against the field keys, with the keys listed as an enum in the JSON
# schema sent to Ollama. (A `Literal` made from a dict's keys cannot be typed for mypy.)
AskField = Annotated[
    str,
    AfterValidator(_askable),
    WithJsonSchema({"type": "string", "enum": list(FIELD_LABELS)}),
]


class DateSlot(BaseModel):
    role: DateRole | None
    phrase: str


class QueryReading(BaseModel):
    """What the model copies out of a prompt. Its JSON schema is the `format` sent to Ollama."""

    intent: Literal["lookup", "list", "find"]
    people: list[str]
    types: list[DocType]
    areas: list[Area]
    field: AskField | None
    date: DateSlot | None
    place: str | None
    words: str


class Query(BaseModel):
    """A reading with people and dates worked out by code. Also the list route's body."""

    model_config = ConfigDict(frozen=True)

    intent: Literal["lookup", "list", "find"]
    people: list[str] = []  # person ids, `home` included; empty means everyone
    types: list[DocType] = []
    areas: list[Area] = []
    field: str | None = None
    role: DateRole | None = None
    range: DateRange | None = None
    place: str | None = None
    words: str = ""
    unread: list[str] = []  # parts code could not resolve, such as "person: Anil"
    backstop_conflicts: int = 0  # slots where the prompt's own words and the model disagreed


def _system_text_v1() -> str:
    types = "\n".join(
        f"- {t.value}: {', '.join(words)}" for t, words in TYPE_WORDS.items() if words
    )
    areas = "\n".join(f"- {a.value}: {label}" for a, label in AREA_LABELS.items())
    fields = "\n".join(f"- {key}: {label}" for key, label in FIELD_LABELS.items())
    roles = sorted({r for per_type in DATE_ROLES.values() for r in per_type})
    head = (
        "You read one question about a family's filed documents into JSON. Fill the slots from "
        "the question. Copy person, time and place words exactly as written; never work out a "
        "date.\n\n"
        'intent: "lookup" when the question asks for one value of one document (a number, an '
        'expiry, an amount); "list" when it asks for every document that matches a condition; '
        '"find" for anything else.\n'
        'people: the names or relations written in the question, as written ("Ravi", "my wife", '
        '"everyone"). Empty when none.\n'
        "types: document types the question is about, from the list below. Empty when unsure.\n"
        "areas: folder areas the question is about, from the list below. Empty when unsure.\n"
        "field: the one value being asked for, from the list below, only for a lookup. null "
        "otherwise.\n"
        "date: when the question has a time condition. role is what the date is about, one of "
        f"{', '.join(roles)}, or null; phrase is the time words as written "
        '("before March", "this year", "FY 2025-26").\n'
        "place: a shop, insurer, hospital or other place named in the question, as written. "
        "null when none.\n"
        'words: the other words worth searching for, such as a product ("fridge").\n\n'
    )
    return (
        f"{head}Document types (type: words people use):\n{types}\n\n"
        f"Areas:\n{areas}\n\nFields (field: label):\n{fields}"
    )


PROMPT_READ_V1 = _system_text_v1()


def _system_text_v2() -> str:
    by_area: dict[Area, list[str]] = {}
    for t, words in TYPE_WORDS.items():
        by_area.setdefault(AREA[t], []).append(
            f"{t.value} ({', '.join(words[:2])})" if words else t.value
        )
    types = "\n".join(f"{a.value}: {'; '.join(items)}" for a, items in by_area.items())
    fields = ", ".join(FIELD_LABELS)
    return (
        "Read one question about a family's filed documents into JSON. Copy people, place and "
        "time words exactly as written; never work out a date.\n\n"
        "intent:\n"
        "- lookup: wants one value of one document, such as a number, a date, a name, an "
        "amount, a doctor, a hospital or a shop. Cues: is, when, what is the X of, how much, "
        'who, which doctor, which shop, "still valid", "when does it expire". Always set field.\n'
        "- list: wants several documents. Cues: which, what, all, any, show me or list with a "
        'plural noun or a group ("policies", "bills", "education documents"), "expiring '
        'before June", "renewals this year".\n'
        "- find: wants one document itself and no value from it. Cues: where is, open, or one "
        "document's name with a person or shop.\n\n"
        'people: names or relations as written ("Ravi", "my wife", "everyone"). A shop, insurer '
        "or hospital is a place, not a person. Empty when none.\n"
        "types: the type ids of the kind of document the question names, from the list below. "
        'Empty when none is named ("anything from Croma").\n'
        'areas: only for a whole group ("insurance papers", "tax documents") with no single '
        "type named. Never fill both for the same words.\n"
        'field: for a lookup, one id from the field list; null otherwise. "still valid", '
        '"expire", "valid till" use expiry_date; "still under warranty" uses warranty_parts; '
        '"document date" uses document_date; "number" on an ID card uses number.\n'
        "date: null unless the question puts a time condition on the documents. Then phrase is "
        'the time words as written ("before March", "this year", "FY 2025-26", "next 6 months"), '
        "never a document name, and role is what the date is about:\n"
        '- expiry: expire, valid till ("insurance expiring before June")\n'
        '- renewal: renew ("renewals this year")\n'
        '- due: due, pay by ("premium due next month")\n'
        '- purchase: bought, purchased, or a bill or invoice from a period ("bought last year", '
        '"bills from last year")\n'
        '- issue: issued ("licences issued in 2020")\n'
        "- document: dated, this year's, last month's, for FY, for any other kind of document "
        '("certificates for last year", "scan reports from last month", "Form 16 for FY '
        '2025-26")\n'
        "place: a shop, insurer, hospital or other place named, as written. null when none.\n"
        'words: other words worth searching for, such as a product or brand ("fridge", "LG"). '
        "Empty when there are none; never a person, a place, a date or a document type.\n\n"
        f"Document types by area (id and words people use):\n{types}\n\n"
        f"Fields (use the id): {fields}\n\n"
        "Examples:\n"
        'Which of Meera\'s insurance papers expire before June? -> {"intent":"list",'
        '"people":["Meera"],"types":[],"areas":["insurance"],"field":null,'
        '"date":{"role":"expiry","phrase":"before June"},"place":null,"words":""}\n'
        'Invoices from Croma this year -> {"intent":"list","people":[],"types":["tax_invoice"],'
        '"areas":[],"field":null,"date":{"role":"purchase","phrase":"this year"},'
        '"place":"Croma","words":""}\n'
        'List all of Dev\'s marksheets -> {"intent":"list","people":["Dev"],'
        '"types":["marksheet"],"areas":[],"field":null,"date":null,"place":null,"words":""}\n'
        'Is Anu\'s passport still valid? -> {"intent":"lookup","people":["Anu"],'
        '"types":["passport"],"areas":[],"field":"expiry_date","date":null,"place":null,'
        '"words":""}\n'
        'Which doctor is on Vik\'s prescription? -> {"intent":"lookup","people":["Vik"],'
        '"types":["prescription"],"areas":[],"field":"doctor","date":null,"place":null,'
        '"words":""}\n'
        'Show me Asha\'s work documents -> {"intent":"list","people":["Asha"],"types":[],'
        '"areas":["work"],"field":null,"date":null,"place":null,"words":""}\n'
        'Show me the Sony TV warranty -> {"intent":"find","people":[],'
        '"types":["warranty_card"],"areas":[],"field":null,"date":null,"place":null,'
        '"words":"Sony TV"}'
    )


PROMPT_READ_V2 = _system_text_v2()
PROMPT_READ = PROMPT_READ_V2  # the prompt the app and the eval use


class PromptReader(Protocol):
    name: str

    def read(self, prompt: str) -> str:
        """The model's JSON text for a prompt."""
        ...


class OllamaPromptReader:
    def __init__(self, client: OllamaClient, model: str, system: str = PROMPT_READ) -> None:
        self._client = client
        self._model = model
        self._system = system
        self.name = f"ollama:{model}"

    def read(self, prompt: str) -> str:
        return self._client.chat_json(
            self._model,
            self._system,
            prompt,
            [],
            QueryReading.model_json_schema(),
            prefill_for(self._model),
            options={"num_ctx": 4096, "num_predict": 400},
        )


def read_prompt(prompt: str, reader: PromptReader) -> QueryReading:
    """One retry on JSON that fails the schema, then plain keywords. A model that is off or
    failing raises `ModelUnavailable`, so the caller can say the reading is off. The prompt is
    never logged and never put in an error."""
    for _ in range(2):
        try:
            raw = reader.read(prompt)
        except (ModelUnavailable, ModelError) as exc:
            raise ModelUnavailable("the prompt reading is off") from exc
        try:
            return QueryReading.model_validate_json(raw)
        except ValidationError:
            continue
    return QueryReading(
        intent="find",
        people=[],
        types=[],
        areas=[],
        field=None,
        date=None,
        place=None,
        words=prompt,
    )


_POSSESSIVE = re.compile(r"['\u2019]s$")
_EVERYONE = {"everyone", "all", "family", "us", "me", "my", "i"}
_HOME = {"home", "house"}
_FORWARD_ROLES = {"expiry", "renewal", "due"}


def _first_word_owner(phrase: str, household: Household) -> str | None:
    words = phrase.split()
    if len(words) != 1:
        return None
    owners = {
        person.id
        for person in household.people
        for name in (person.name, *person.aliases)
        if normalise_name(name).split()[:1] == words
    }
    return next(iter(owners)) if len(owners) == 1 else None


def _person(phrase: str, household: Household) -> tuple[str | None, bool]:
    """(person id or None, whether the phrase means no filter)."""
    text = _POSSESSIVE.sub("", phrase.strip().lower())
    if text in _EVERYONE:
        return None, True
    if text in _HOME:
        return "home", False
    pid = match_person(text, household).person_id or _first_word_owner(
        normalise_name(text), household
    )
    return pid, False


def _selected(types: list[DocType], areas: list[Area]) -> set[DocType]:
    return set(types) | {t for t, area in AREA.items() if area in areas}


_ROLE_WORDS: tuple[tuple[DateRole, re.Pattern[str]], ...] = (
    ("expiry", re.compile(r"\bexpir\w*|\bvalid (?:till|until|upto|up to)\b")),
    ("renewal", re.compile(r"\brenew\w*")),
    ("due", re.compile(r"\bdue\b|\bpay by\b")),
    ("purchase", re.compile(r"\bbought\b|\bpurchase[ds]?\b")),
    ("issue", re.compile(r"\bissued\b")),
    ("document", re.compile(r"\bdated\b|\bthis year's\b|\bfor fy\b")),
)
_WORD = re.compile(r"[\w'\u2019/-]+")
_MAX_NAME_WORDS = 3
_MAX_DATE_WORDS = 6


def _words(prompt: str) -> list[str]:
    return [_POSSESSIVE.sub("", w.strip("'\u2019-/")) for w in _WORD.findall(prompt.lower())]


def _scan_people(prompt: str, household: Household) -> list[str]:
    """Household names and aliases in the prompt, longest phrase first, each word used once."""
    words = _words(prompt)
    used = [False] * len(words)
    found: list[str] = []
    for size in range(min(_MAX_NAME_WORDS, len(words)), 0, -1):
        for start in range(len(words) - size + 1):
            phrase = " ".join(words[start : start + size])
            if any(used[start : start + size]) or phrase in _EVERYONE | _HOME:
                continue
            pid, _ = _person(phrase, household)
            if pid is not None and pid != "home":
                used[start : start + size] = [True] * size
                if pid not in found:
                    found.append(pid)
    return found


def _scan_date(prompt: str, today: date) -> tuple[DateSlot, DateRange] | None:
    """The first date phrase code can read in the prompt (longest span first), with the role
    its cue words give. A bare "may" is the verb, not the month."""
    words = _words(prompt)
    lowered = prompt.lower().replace("\u2019", "'")
    for size in range(min(_MAX_DATE_WORDS, len(words)), 0, -1):
        for start in range(len(words) - size + 1):
            phrase = " ".join(words[start : start + size])
            if phrase == "may":
                continue
            span = parse_date_phrase(phrase, today)
            if span is None or (span.start and span.end and span.start > span.end):
                continue
            role = next((r for r, cue in _ROLE_WORDS if cue.search(lowered)), "document")
            return DateSlot(role=role, phrase=phrase), span
    return None


def _scan_types(prompt: str) -> list[DocType]:
    """Types whose words appear whole in the prompt, the longest phrase first so that
    "extended warranty" does not also count as "warranty"."""
    text = " ".join(_words(prompt))
    phrases = sorted(
        ((w, t) for t, ws in TYPE_WORDS.items() for w in ws), key=lambda p: len(p[0]), reverse=True
    )
    found: list[DocType] = []
    for phrase, doc_type in phrases:
        pattern = rf"(?<!\w){re.escape(phrase)}(?!\w)"
        if re.search(pattern, text):
            text = re.sub(pattern, " ", text)
            if doc_type not in found:
                found.append(doc_type)
    return found


def resolve(reading: QueryReading, household: Household, today: date, prompt: str = "") -> Query:
    """Work out people and dates. With the prompt text, code fills the closed-class slots the
    model left empty (a household name, a date phrase, a document type word). The model's own
    slot always wins; a slot where the prompt says something else is counted as a conflict."""
    conflicts = 0
    slot = reading.date
    types = reading.types
    backstop_people: list[str] = []
    if prompt:
        seen = _scan_people(prompt, household)
        if not reading.people:
            backstop_people = seen
        elif seen and set(seen) != {_person(p, household)[0] for p in reading.people}:
            conflicts += 1
        scanned = _scan_date(prompt, today)
        if scanned is not None and slot is None:
            slot = scanned[0]
        elif (
            scanned is not None
            and slot is not None
            and parse_date_phrase(slot.phrase, today) != scanned[1]
        ):
            conflicts += 1
        found_types = _scan_types(prompt)
        if found_types and not reading.types and not reading.areas:
            types = found_types
        elif found_types and set(found_types) != set(reading.types):
            conflicts += 1
    # A listed type beats its area: the model often names both, and the union would widen the
    # question to the whole area.
    areas = [a for a in reading.areas if not any(AREA[t] is a for t in types)]
    unread: list[str] = []
    people: list[str] = list(backstop_people)
    for phrase in reading.people:
        pid, no_filter = _person(phrase, household)
        if pid is not None:
            if pid not in people:
                people.append(pid)
        elif not no_filter:
            unread.append(f"person: {phrase}")
    role: DateRole | None = None
    span: DateRange | None = None
    if slot is not None:
        role = slot.role
        selected = _selected(types, areas)
        if (
            role not in (None, "document")
            and selected
            and not any(role in DATE_ROLES[t] for t in selected)
        ):
            role = "document"  # none of the types has a date of that kind
        span = parse_date_phrase(slot.phrase, today)
        if span is not None and role in _FORWARD_ROLES and span.start is None and span.end:
            # a forward question looks ahead: an end only means "from today to then"
            span = DateRange(start=today, end=span.end)
        if span is None or (span.start and span.end and span.start > span.end):
            span = None  # never an inverted range
            unread.append(f"date: {slot.phrase}")
    return Query(
        intent=reading.intent,
        people=people,
        types=types,
        areas=areas,
        field=reading.field,
        role=role,
        range=span,
        place=reading.place,
        words=reading.words,
        unread=unread,
        backstop_conflicts=conflicts,
    )
