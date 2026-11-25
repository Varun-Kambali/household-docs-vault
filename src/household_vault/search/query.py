"""A person's prompt, read into a structured query.

A small local model copies the words of the prompt into slots (people, types, field, date and
place phrases). Code then works out who the people are and what the dates mean, and reports
anything it could not read. The model sees only the prompt and the fixed vocabulary, never a
document, and never works out a date.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from datetime import date
from typing import Annotated, Literal, Protocol

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, WithJsonSchema

from household_vault.doctypes import AREA, Area, DocType
from household_vault.people import Household, match_person, normalise_name
from household_vault.reading.engines import prefill_for
from household_vault.reading.ollama import ModelError, ModelUnavailable, OllamaClient
from household_vault.search.dates import DateRange, parse_date_phrase
from household_vault.search.vocab import (
    AREA_LABELS,
    DATE_ROLES,
    FIELD_LABELS,
    FIND_CUES,
    GENERIC_WORDS,
    LIST_CUE_WORDS,
    LIST_OPENERS,
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
    """A reading with people and dates worked out by code. Also the list route's body.

    `backstop_conflicts` is for the eval only: it is left out of every serialised form, so the
    API and the app never show it.
    """

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
    # slots where the prompt's own words and the model disagreed; never part of the stored form
    backstop_conflicts: int = Field(default=0, exclude=True)


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
_DETERMINERS = {"the", "a", "an", "our", "my"}


def _without_determiners(phrase: str) -> str:
    """The phrase without the articles and determiners it begins with."""
    tokens = phrase.split()
    while tokens and tokens[0].strip("'\u2019").lower() in _DETERMINERS:
        tokens.pop(0)
    return " ".join(tokens)


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


def _inside(phrase: str, outer: str) -> bool:
    """Whether the words of `phrase` appear in a row inside the words of `outer`."""
    want, words = _words(phrase), _words(outer)
    return bool(want) and any(
        words[i : i + len(want)] == want for i in range(len(words) - len(want) + 1)
    )


def _occupied(prompt_words: list[str], *texts: str | None) -> set[int]:
    """Word positions of the prompt that lie inside a run of words the model copied into a
    slot (its place or its words)."""
    taken: set[int] = set()
    for text in texts:
        want = _words(text) if text else []
        for i in range(len(prompt_words) - len(want) + 1) if want else ():
            if prompt_words[i : i + len(want)] == want:
                taken.update(range(i, i + len(want)))
    return taken


def _people_spans(
    words: list[str], household: Household, skip: set[int] | None = None
) -> tuple[list[str], list[bool]]:
    """Household names and aliases among `words`, longest phrase first, each word used once.
    Returns the person ids found and which word positions they used (words in `skip` are
    never names)."""
    used = [i in (skip or set()) for i in range(len(words))]
    mine = list(used)
    found: list[str] = []
    for size in range(min(_MAX_NAME_WORDS, len(words)), 0, -1):
        for start in range(len(words) - size + 1):
            phrase = " ".join(words[start : start + size])
            if any(used[start : start + size]) or phrase in _EVERYONE | _HOME:
                continue
            pid, _ = _person(phrase, household)
            if pid is not None and pid != "home":
                used[start : start + size] = [True] * size
                mine[start : start + size] = [True] * size
                if pid not in found:
                    found.append(pid)
    return found, [m and i not in (skip or set()) for i, m in enumerate(mine)]


Places = Mapping[str, Collection[DocType]]


def _as_places(places: Places | Sequence[str]) -> Places:
    """Stored place values with the document types each is stored on (none known for a bare
    list of values)."""
    if isinstance(places, Mapping):
        return places
    return {v: frozenset() for v in places}


def _stored_place(
    phrase: str,
    places: Places,
    types: Collection[DocType] = (),
    possessive: bool = False,
) -> bool:
    """Whether the phrase is a stored place. Several words match when they appear whole and in a
    row inside a stored value; a lone word that is a whole value matches. A lone word that is
    only one word of a longer value ("Anil" in "Anil Diagnostics") may still be a person, so it
    matches only when the query names a type the value is stored on, or, with no type named,
    when the prompt does not write it as a possessive."""
    want = _words(phrase)
    if not want:
        return False
    if len(want) > 1:
        return any(_inside(phrase, v) for v in places)
    if any(_words(v) == want for v in places):
        return True
    holders = [v for v in places if want[0] in _words(v)]
    if types:
        return any(set(types) & set(places[v]) for v in holders)
    return bool(holders) and not possessive


def _place_positions(prompt_words: list[str], places: Collection[str]) -> set[int]:
    """Word positions of the prompt that lie inside a whole stored place value."""
    return _occupied(prompt_words, *places)


def _scan_people(prompt: str, household: Household, skip: set[int] | None = None) -> list[str]:
    """Household names and aliases in the prompt. Words in `skip` (inside the model's place)
    are not names."""
    return _people_spans(_words(prompt), household, skip)[0]


def _name_and_rest(phrase: str, household: Household) -> tuple[list[str], str]:
    """A household name or alias inside a longer phrase: the person ids and the words left."""
    tokens = _WORD.findall(phrase)
    found, named = _people_spans(_words(phrase), household)
    return found, " ".join(t for t, hit in zip(tokens, named, strict=True) if not hit)


def _nearest_role(lowered: str, phrase: str) -> DateRole:
    """The role of the cue word closest to the date phrase; the document date with no cue."""
    at = lowered.find(phrase)
    best: tuple[int, DateRole] | None = None
    for role, cue in _ROLE_WORDS:
        for m in cue.finditer(lowered):
            gap = m.start() if at < 0 else max(at - m.end(), m.start() - (at + len(phrase)), 0)
            if best is None or gap < best[0]:
                best = (gap, role)
    return best[1] if best else "document"


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
            role = _nearest_role(lowered, phrase)
            return DateSlot(role=role, phrase=phrase), span
    return None


_NO_PLURAL_UNDER = 4  # a short code (pan, dl, rc, ec, amc) is never made plural
_CARD_AFTER = {"warranty", "guarantee", "service"}


def _plurals(word: str, alone: bool) -> set[str]:
    """The word and its plural forms: -s, -ies after a consonant and y, -es after s, x, z, ch
    or sh. Nothing for a short code standing alone (a phrase's last word, as in "form 16", may
    take an s)."""
    forms = {word}
    if alone and len(word) < _NO_PLURAL_UNDER:
        return forms
    if word.endswith("y") and word[-2] not in "aeiou":
        forms.add(word[:-1] + "ies")
    elif word.endswith(("s", "x", "z", "ch", "sh")):
        forms.add(word + "es")
    else:
        forms.add(word + "s")
    return forms


def _match_types(words: list[str], skip: set[int] | None = None) -> tuple[list[DocType], set[int]]:
    """Types whose words appear whole in the prompt, the longest phrase first and no word used
    twice, so "extended warranty" does not also count as "warranty". Words in `skip` (inside
    the model's place or words) are not type words, and a bare "card" next to "warranty",
    "guarantee", "service" or another matched type word is part of that name. Also returns the
    word positions the matches used."""
    taken = set(skip or ())
    phrases = sorted(
        ((tuple(w.split()), t) for t, ws in TYPE_WORDS.items() for w in ws),
        key=lambda p: len(" ".join(p[0])),
        reverse=True,
    )
    found: list[DocType] = []

    def match(phrase: tuple[str, ...], start: int) -> bool:
        end = start + len(phrase)
        if end > len(words) or any(i in taken for i in range(start, end)):
            return False
        return list(phrase[:-1]) == words[start : end - 1] and words[end - 1] in _plurals(
            phrase[-1], len(phrase) == 1
        )

    bare_card: DocType | None = None
    for phrase, doc_type in phrases:
        if phrase == ("card",):
            bare_card = doc_type
            continue
        for start in range(len(words)):
            if match(phrase, start):
                taken.update(range(start, start + len(phrase)))
                if doc_type not in found:
                    found.append(doc_type)
    if bare_card is not None:
        for start in range(len(words)):
            before = start - 1
            if match(("card",), start) and (
                before < 0 or (words[before] not in _CARD_AFTER and before not in taken)
            ):
                found.append(bare_card)
                taken.add(start)
                break
    return found, taken


_FUZZY_FROM = 6  # a cue word this long may carry one typo; shorter ones never do


def _one_edit(a: str, b: str) -> bool:
    """Whether the two words differ by one insertion, deletion, substitution or swap."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        return len(diff) == 1 or (
            len(diff) == 2
            and diff[1] == diff[0] + 1
            and a[diff[0]] == b[diff[1]]
            and a[diff[1]] == b[diff[0]]
        )
    short, long = sorted((a, b), key=len)
    return any(long[:i] + long[i + 1 :] == short for i in range(len(long)))


def _is_cue_word(word: str, cue: str) -> bool:
    """The cue word, or it with one typo. The singular of a plural cue ("record" for "records")
    is a different word, not a typo."""
    if word == cue:
        return True
    if len(cue) < _FUZZY_FROM or len(word) < _FUZZY_FROM - 1 or cue in (word + "s", word[:-1]):
        return False
    return _one_edit(word, cue)


def _has_phrase(words: list[str], phrases: Sequence[tuple[str, ...]], anywhere: bool) -> bool:
    """Whether the words hold one of the phrases (at the start only unless `anywhere`)."""
    for phrase in phrases:
        size = len(phrase)
        starts = range(len(words) - size + 1) if anywhere else range(min(1, len(words) - size + 1))
        if any(tuple(words[i : i + size]) == phrase for i in starts):
            return True
    return False


def _plural_type_hit(words: list[str], skip: set[int]) -> bool:
    """Whether a type word stands in its plural form ("warranties", "bills") outside `skip`."""
    for t_words in TYPE_WORDS.values():
        for text in t_words:
            phrase = text.split()
            last = phrase[-1]
            plural = _plurals(last, len(phrase) == 1) - {last}
            size = len(phrase)
            for start in range(len(words) - size + 1):
                span = range(start, start + size)
                if (
                    not any(i in skip for i in span)
                    and words[start : start + size - 1] == phrase[:-1]
                    and words[start + size - 1] in plural
                ):
                    return True
    return False


def _asks_for_one_value(words: list[str]) -> bool:
    """ "Which shop issued ..." asks for one value; "which bills" and "which of" ask for a list."""
    return (
        len(words) > 1
        and words[0] == "which"
        and not words[1].endswith("s")
        and words[1] not in ("of", "do")
    )


def _list_cue(words: list[str], skip: set[int]) -> bool:
    """Whether the prompt asks for many documents and for no one in particular: a list cue word,
    a plural type word or an opening phrase, with none of the find cues."""
    if _has_phrase(words, FIND_CUES, anywhere=True):
        return False
    return (
        any(
            _is_cue_word(w, cue)
            for i, w in enumerate(words)
            if i not in skip
            for cue in LIST_CUE_WORDS
        )
        or _plural_type_hit(words, skip)
        or (_has_phrase(words, LIST_OPENERS, anywhere=False) and not _asks_for_one_value(words))
    )


def _scan_types(prompt: str, skip: set[int] | None = None) -> list[DocType]:
    """Types whose words appear whole in the prompt (see `_match_types`)."""
    return _match_types(_words(prompt), skip)[0]


def _without_type_words(phrase: str) -> tuple[str, set[DocType]]:
    """The phrase without its type words (and generic ones such as "policy"), and the types
    those words name: "Tungabhadra life insurance policy" gives "Tungabhadra" and life_policy."""
    tokens = _WORD.findall(phrase)
    words = _words(phrase)
    found, taken = _match_types(words)
    kept = [
        _POSSESSIVE.sub("", t.strip("'\u2019-/"))
        for i, (t, w) in enumerate(zip(tokens, words, strict=True))
        if i not in taken and w not in GENERIC_WORDS
    ]
    return " ".join(k for k in kept if k), set(found)


def _place_of(phrase: str, places: Places, types: Collection[DocType], prompt: str) -> str | None:
    """The phrase as a stored place, or None. Type words are dropped first, and the types they
    name count with the query's own."""
    stripped, named = _without_type_words(phrase)
    if len(_words(stripped)) < len(_words(phrase)) and _stored_place(phrase, places, types):
        return phrase  # stripping cut it short, but the whole phrase is a stored place
    if not stripped:
        return None
    lone = _words(stripped)
    possessive = len(lone) == 1 and bool(
        re.search(rf"\b{re.escape(lone[0])}['\u2019]s\b", prompt.lower())
        or _POSSESSIVE.search(phrase.strip().lower())
    )
    return stripped if _stored_place(stripped, places, {*types, *named}, possessive) else None


def resolve(
    reading: QueryReading,
    household: Household,
    today: date,
    prompt: str = "",
    places: Places | Sequence[str] = (),
) -> Query:
    """Work out people and dates. With the prompt text, code fills the closed-class slots the
    model left empty (a household name, a date phrase, a document type word). The model's own
    slot always wins; a slot where the prompt says something else is counted as a conflict.
    `places` are the place values stored in the vault: a person phrase that is one of them is
    a place, and a stored place found in the prompt is never read as a name or a type."""
    conflicts = 0
    places = _as_places(places)
    slot = reading.date
    types = reading.types
    backstop_people: list[str] = []
    if prompt:
        prompt_words = _words(prompt)
        stored = _place_positions(prompt_words, places)
        seen = _scan_people(prompt, household, _occupied(prompt_words, reading.place) | stored)
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
            and parse_date_phrase(slot.phrase, today) is None
        ):
            # the model copied words code cannot read ("expiring before June"): keep its role and
            # read the date from the prompt itself, but only from words inside the model's own
            # phrase; a second date elsewhere in the prompt is not the one it meant
            if _inside(scanned[0].phrase, slot.phrase):
                slot = DateSlot(role=slot.role, phrase=scanned[0].phrase)
        elif (
            scanned is not None
            and slot is not None
            and parse_date_phrase(slot.phrase, today) != scanned[1]
        ):
            conflicts += 1
        found_types = _scan_types(
            prompt, _occupied(prompt_words, reading.place, reading.words) | stored
        )
        if (
            found_types
            and not reading.types
            and all(AREA[t] in reading.areas or not reading.areas for t in found_types)
        ):
            # nothing named, or only the area that holds the type the prompt names
            types = found_types
        elif found_types and set(found_types) != set(reading.types):
            conflicts += 1
    # A listed type beats its area: the model often names both, and the union would widen the
    # question to the whole area.
    areas = [a for a in reading.areas if not any(AREA[t] is a for t in types)]
    intent = reading.intent
    if prompt and intent != "list" and reading.field is None:
        prompt_words = _words(prompt)
        if _list_cue(
            prompt_words,
            _place_positions(prompt_words, places) | _occupied(prompt_words, reading.place),
        ):
            intent = "list"  # the prompt asks for many documents and the model did not
            conflicts += 1
    unread: list[str] = []
    people: list[str] = list(backstop_people)
    place, words = reading.place, reading.words
    for phrase in reading.people:
        pid, no_filter = _person(phrase, household)
        if pid is not None:
            if pid not in people:
                people.append(pid)
        elif not no_filter:
            phrase = _without_determiners(phrase)
            if not phrase:
                continue  # only an article was copied: nothing was named
            pid, no_filter = _person(phrase, household)
            if pid is not None:
                if pid not in people:
                    people.append(pid)
                continue
            if no_filter:
                continue
            as_place = _place_of(phrase, places, types, prompt)
            if as_place is not None:
                if place is None or not place.strip():
                    place = as_place
                elif not _inside(as_place, place):
                    words = f"{words} {as_place}".strip()
                continue
            named, rest = _name_and_rest(phrase, household)
            rest_place = _place_of(rest, places, types, prompt) if rest else None
            if not named or (rest and rest_place is None):
                # nobody named, or the other words are not a stored place (an outsider's
                # surname): leave the whole phrase unread so a lookup declines
                unread.append(f"person: {phrase}")
                continue
            # the model put a name and other words (a shop, an employer) in one person slot
            conflicts += 1
            people.extend(p for p in named if p not in people)
            if rest_place and (place is None or not place.strip()):
                place = rest_place
            elif rest_place:
                words = f"{words} {rest_place}".strip()
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
        intent=intent,
        people=people,
        types=types,
        areas=areas,
        field=reading.field,
        role=role,
        range=span,
        place=place,
        words=words,
        unread=unread,
        backstop_conflicts=conflicts,
    )
