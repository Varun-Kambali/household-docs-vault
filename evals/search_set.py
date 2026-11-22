"""The search eval set: questions about a synthetic vault, with the truth that scores them.

The vault of a split is the split's eval-v1 documents (photo variant) plus the same split of the
two extra sets (`search-x1`, `search-x2`, clean variant). A question is built from truth fields
only, so its answer is known without running any search. Nothing here calls a model.

Kinds: a lookup asks for one value of one document, a find names a document, a list asks for
every document under a condition, and a none asks for something the vault does not hold. Only a
document the app would file is ever asked about: one whose truth expects a question (an outsider,
unclear initials, a missing required field) is in the vault but is neither a target nor an
expected list member.
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, JsonValue
from vault_synth.data import plus_year
from vault_synth.model import SynthDoc
from vault_synth.sets import Split, load_set

from household_vault.doctypes import AREA, DATE_FIELD, Area, DocType
from household_vault.people import Household, load_household, match_person, normalise_name
from household_vault.search.dates import DateRange
from household_vault.search.query import DateSlot, Query, QueryReading, resolve
from household_vault.search.vocab import (
    DATE_ROLES,
    FIELD_LABELS,
    PLACE_FIELDS,
    TYPE_LABELS,
    DateRole,
)

EVAL_TODAY = date(2026, 11, 20)
ROOT = Path(__file__).resolve().parent
EVAL_V1 = ROOT / "datasets" / "eval-v1"
SEARCH_DIR = ROOT / "datasets" / "search-v1"
EXTRA_SETS = ("search-x1", "search-x2")
SET_SEED = 27
SPLITS: tuple[Split, ...] = ("val", "test")

Kind = Literal["lookup", "find", "list", "none"]
Style = Literal["question", "terse", "typo", "synonym"]
Origin = Literal["eval-v1", "extra"]
Box = tuple[float, float, float, float]

N_LOOKUP, N_FIND, N_LIST, N_NONE = 100, 50, 40, 20
MAX_LIST_MEMBERS = 40

# Fields whose value is a yes or no worked out from a date and EVAL_TODAY.
STATUS_VALID = "status.valid"
STATUS_WARRANTY = "status.warranty"
STATUS_TYPES = frozenset(
    {
        DocType.life_policy,
        DocType.health_policy,
        DocType.vehicle_policy,
        DocType.home_policy,
        DocType.travel_policy,
        DocType.gadget_policy,
        DocType.accident_policy,
        DocType.passport,
        DocType.driving_licence,
        DocType.puc_certificate,
        DocType.rent_agreement,
        DocType.extended_warranty,
        DocType.amc,
    }
)


class Question(BaseModel):
    id: str
    split: Split
    kind: Kind
    origin: Origin
    style: Style
    prompt: str
    targets: list[str]
    field: str | None = None
    value: JsonValue = None
    page: int | None = None
    box: Box | None = None
    query: Query | None = None
    expected: list[str] | None = None


# --- the vault -------------------------------------------------------------------------------


def search_vault_docs(split: Split) -> list[SynthDoc]:
    """The split's eval-v1 documents in the photo variant (a card with a back lists both files,
    as the filing eval drops them), then the split's documents of each extra set."""
    docs = [d for d in load_set(EVAL_V1) if d.split == split and d.variant == "photo"]
    for name in EXTRA_SETS:
        docs += [d for d in load_set(SEARCH_DIR / "extra" / name) if d.split == split]
    return docs


def origin_of(doc: SynthDoc) -> Origin:
    return "eval-v1" if doc.set_name == "eval-v1" else "extra"


def is_filed(doc: SynthDoc) -> bool:
    """A document whose truth expects no question files by itself and can be asked about."""
    return not doc.expected_ask


# --- truth -----------------------------------------------------------------------------------


def _as_date(value: JsonValue) -> date | None:
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def status_source(doc_type: DocType, field_name: str) -> str | None:
    """The date field a status question reads."""
    if field_name == STATUS_VALID:
        return DATE_ROLES[doc_type].get("expiry")
    if field_name == STATUS_WARRANTY:
        return "purchase_date"
    return None


def _warranty_end(doc: SynthDoc) -> date | None:
    start = _as_date(doc.fields.get("purchase_date"))
    parts = doc.fields.get("warranty_parts")
    if start is None or not isinstance(parts, list):
        return None
    years: dict[str, int] = {}
    for part in parts:
        name = part.get("part") if isinstance(part, dict) else None
        if isinstance(part, dict) and isinstance(name, str):
            try:
                years[name.lower()] = int(str(part.get("years")))
            except ValueError:
                continue
    if not years:
        return None
    # the cover on the product itself; when no part is called that, the longest cover
    return plus_year(start, years.get("product", max(years.values())))


def truth_value(doc: SynthDoc, field_name: str | None, today: date = EVAL_TODAY) -> JsonValue:
    """The truth the question asks for: a stored field, or a status worked out at `today`."""
    if field_name is None:
        return None
    if field_name == STATUS_VALID:
        source = status_source(doc.doc_type, field_name)
        end = _as_date(doc.fields.get(source)) if source else None
        return None if end is None else end >= today
    if field_name == STATUS_WARRANTY:
        end = _warranty_end(doc)
        return None if end is None else end >= today
    return doc.fields.get(field_name)


def _has_phrase(text: str, phrase: str) -> bool:
    """Whether the words of `phrase` appear in `text` in a row, both after `normalise_name`."""
    words, want = normalise_name(text).split(), normalise_name(phrase).split()
    if not want:
        return False
    return any(words[i : i + len(want)] == want for i in range(len(words) - len(want) + 1))


def _place_values(doc: SynthDoc) -> list[str]:
    values = (doc.fields.get(f) for f in PLACE_FIELDS[doc.doc_type])
    return [v for v in values if isinstance(v, str)]


def _in_people(doc: SynthDoc, people: Iterable[str]) -> bool:
    ids = set(people)
    return doc.owner in ids or any(p in ids for p in doc.linked_people)


def _role_date(doc: SynthDoc, role: DateRole) -> date | None:
    if role == "document":
        name = DATE_FIELD.get(doc.doc_type)
    else:
        name = DATE_ROLES[doc.doc_type].get(role)
    return _as_date(doc.fields.get(name)) if name else None


def _in_range(value: date, span: DateRange) -> bool:
    return (span.start is None or value >= span.start) and (span.end is None or value <= span.end)


def apply_query(query: Query, docs: Sequence[SynthDoc]) -> list[str]:
    """The truth side of a list prompt, from truth fields.

    People match the owner or a linked person; areas expand to their types and, with `types`,
    either one fits; the range applies to the field of the query's role (`document` is the
    document date, and no role means the document date); a place is a contained phrase of the
    type's place field. A document that expects a question is not filed and never matches.
    """
    wanted_types = set(query.types)
    wanted_areas = set(query.areas)
    out: list[str] = []
    for doc in docs:
        if not is_filed(doc):
            continue
        if query.people and not _in_people(doc, query.people):
            continue
        if (wanted_types or wanted_areas) and not (
            doc.doc_type in wanted_types or AREA[doc.doc_type] in wanted_areas
        ):
            continue
        place = query.place
        if place and not any(_has_phrase(v, place) for v in _place_values(doc)):
            continue
        if query.range is not None:
            when = _role_date(doc, query.role or "document")
            if when is None or not _in_range(when, query.range):
                continue
        out.append(doc.doc_id)
    return out


# --- wording ---------------------------------------------------------------------------------

_GENERIC_TAIL = frozenset(
    {"limited", "ltd", "company", "insurance", "assurance", "general", "life", "health"}
    | {"private", "pvt", "hospital", "clinic", "centre", "center"}
)
PRODUCT_NOUNS = (
    "refrigerator",
    "washing machine",
    "television",
    "air conditioner",
    "microwave oven",
)
_BRANDS = frozenset({"lg", "samsung", "sony", "voltas", "whirlpool"})
NOUN_OVERRIDE = {DocType.tax_invoice: "invoice"}

# Words a person types for the same thing; the fixed table of the synonym style.
SYNONYMS: tuple[tuple[str, str], ...] = (
    ("health insurance policy", "mediclaim"),
    ("health insurance", "mediclaim"),
    ("refrigerator", "fridge"),
    ("television", "TV"),
    ("vehicle", "car"),
    ("gadget", "mobile"),
)

PLURAL: dict[DocType, str] = {
    DocType.tax_invoice: "invoices",
    DocType.payslip: "payslips",
    DocType.prescription: "prescriptions",
    DocType.lab_report: "lab reports",
    DocType.utility_bill: "utility bills",
    DocType.card_statement: "card statements",
    DocType.hospital_bill: "hospital bills",
    DocType.health_policy: "health insurance policies",
    DocType.vehicle_policy: "vehicle insurance policies",
    DocType.life_policy: "life insurance policies",
    DocType.warranty_card: "warranty cards",
    DocType.marksheet: "marksheets",
    DocType.certificate: "certificates",
    DocType.passport: "passports",
    DocType.scan_report: "scan reports",
    DocType.form_16: "Form 16s",
}
GROUPS: dict[str, tuple[DocType, ...]] = {
    "warranties": (DocType.warranty_card, DocType.extended_warranty),
}
AREA_PHRASE: dict[Area, str] = {
    Area.insurance: "insurance papers",
    Area.purchases: "purchases",
    Area.identity: "identity documents",
    Area.vehicle: "vehicle papers",
    Area.work: "work documents",
    Area.education: "education documents",
    Area.tax: "tax documents",
    Area.cards: "card documents",
    Area.medical: "medical records",
    Area.property: "property documents",
    Area.rent: "rent papers",
    Area.utilities: "utility bills",
}

# field -> (full question, terse); {s} is the subject ("Kavita's PAN card" or "the PAN card"),
# {sn} the same without the possessive.
Ask = tuple[str, str]
_DEFAULT_ASK: Ask = ("What is the {label} on {s}?", "{sn} {label}")
ASK: dict[str, Ask] = {
    "end_date": ("When does {s} expire?", "{sn} expiry date"),
    "expiry_date": ("When does {s} expire?", "{sn} expiry date"),
    "start_date": ("When did {s} start?", "{sn} start date"),
    "issue_date": ("When was {s} issued?", "{sn} issue date"),
    "premium_due_date": ("When is the next premium due on {s}?", "{sn} premium due date"),
    "payment_due_date": ("When is the payment due on {s}?", "{sn} payment due date"),
    "period_end": ("When does the cover on {s} end?", "{sn} cover end date"),
    "next_visit": ("When is the next visit on {s}?", "{sn} next visit"),
    "seller": ("Which shop issued {s}?", "{sn} shop"),
    "insurer": ("Which insurer issued {s}?", "{sn} insurer"),
    "bank": ("Which bank is on {s}?", "{sn} bank"),
    "employer": ("Which employer is on {s}?", "{sn} employer"),
    "doctor": ("Which doctor is on {s}?", "{sn} doctor"),
    "hospital": ("Which hospital is on {s}?", "{sn} hospital"),
    "lab": ("Which lab is on {s}?", "{sn} lab"),
    "issuer": ("Which institution issued {s}?", "{sn} issuer"),
    "provider": ("Which provider issued {s}?", "{sn} provider"),
    "amount": ("What is the total amount on {s}?", "{sn} amount"),
    "premium": ("How much is the premium on {s}?", "{sn} premium"),
    "rent_amount": ("How much is the monthly rent on {s}?", "{sn} monthly rent"),
    "last4": ("What are the last four digits on {s}?", "{sn} last four digits"),
    "number": ("What is the number on {s}?", "{sn} number"),
    STATUS_VALID: ("Is {s} still valid?", "{sn} still valid"),
    STATUS_WARRANTY: ("Is {s} still under warranty?", "{sn} under warranty"),
}
# Fields a lookup may ask for. Names, addresses, lists and secrets (a card's number and CVV)
# are never asked.
ASKABLE: tuple[str, ...] = (
    "policy_number",
    "insurer",
    "premium",
    "sum_insured",
    "start_date",
    "end_date",
    "premium_due_date",
    "nominee",
    "registration_number",
    "idv",
    "seller",
    "invoice_number",
    "invoice_date",
    "model",
    "serial_number",
    "amount",
    "brand",
    "purchase_date",
    "period_end",
    "number",
    "date_of_birth",
    "issue_date",
    "expiry_date",
    "certificate_number",
    "document_date",
    "tag_id",
    "employer",
    "net_pay",
    "designation",
    "issuer",
    "credential_id",
    "roll_number",
    "assessment_year",
    "acknowledgement_number",
    "section",
    "bank",
    "last4",
    "statement_date",
    "payment_due_date",
    "total_due",
    "credit_limit",
    "annual_fee",
    "hospital",
    "doctor",
    "date",
    "next_visit",
    "lab",
    "department",
    "khata_number",
    "receipt_number",
    "rent_amount",
    "deposit",
    "provider",
    "consumer_number",
)
SECRET = {(DocType.card_front, "number"), (DocType.card_front, "cvv")}
# What a question about this field must not also use to pick the document.
PLACE_LIKE = {"seller", "insurer", "bank", "employer", "hospital", "lab", "issuer", "provider"}
PRODUCT_LIKE = {"brand", "product", "model"}


def short_place(name: str) -> str:
    """The way a person says a place: the name without its trailing 'Insurance Company Limited'."""
    words = name.split()
    while len(words) > 1 and words[-1].lower() in _GENERIC_TAIL:
        words.pop()
    return " ".join(words)


def _first(name: str) -> str:
    return name.split()[0]


def _normal_text(text: str) -> str:
    return " ".join(re.sub(r"[\W_]+", " ", text.casefold()).split())


@dataclass(frozen=True)
class Cons:
    """What picks a document out: its type and optional person, place, brand and product."""

    doc_type: DocType
    person: str | None = None
    place: str | None = None
    brand: str | None = None
    product: str | None = None


def _brand_of(doc: SynthDoc) -> str | None:
    brand = doc.fields.get("brand")
    if isinstance(brand, str):
        return brand
    product = doc.fields.get("product")
    if isinstance(product, str) and _first(product).lower() in _BRANDS:
        return _first(product)
    return None


def _product_of(doc: SynthDoc) -> str | None:
    product = doc.fields.get("product")
    if not isinstance(product, str):
        return None
    text = _normal_text(product)
    return next((n for n in PRODUCT_NOUNS if n in text), None)


def fits(doc: SynthDoc, cons: Cons) -> bool:
    if not is_filed(doc) or doc.doc_type != cons.doc_type:
        return False
    if cons.person is not None and not _in_people(doc, [cons.person]):
        return False
    if cons.place is not None and not any(_has_phrase(v, cons.place) for v in _place_values(doc)):
        return False
    if cons.brand is not None:
        brand = _brand_of(doc) or ""
        if not _has_phrase(f"{brand} {doc.fields.get('product') or ''}", cons.brand):
            return False
    if cons.product is not None:
        product = doc.fields.get("product")
        if not isinstance(product, str) or cons.product not in _normal_text(product):
            return False
    return True


def _subject(cons: Cons, household: Household, rng: random.Random) -> tuple[str, str, set[str]]:
    """(subject with possessive or 'the', subject without, tokens a typo must not touch)."""
    noun = NOUN_OVERRIDE.get(cons.doc_type, TYPE_LABELS[cons.doc_type])
    if cons.doc_type is DocType.tax_invoice and rng.random() < 0.3:
        noun = "bill"
    words = [w for w in (cons.place, cons.brand, cons.product, noun) if w]
    body = " ".join(words)
    protect = {t.casefold() for w in (cons.place, cons.brand) if w for t in w.split()}
    if cons.person is None:
        return f"the {body}", body, protect
    first = _first(household.by_id(cons.person).name)
    protect.add(first.casefold())
    return f"{first}'s {body}", f"{first} {body}", protect


def _typo(text: str, protect: set[str], rng: random.Random) -> str | None:
    """One letter wrong in one plain word (not a name, place or brand), or None if none fits."""
    spots = [
        m
        for m in re.finditer(r"[A-Za-z]{5,}", text)
        if m.group(0).casefold() not in protect and m.group(0).casefold() != "'s"
    ]
    if not spots:
        return None
    m = rng.choice(spots)
    word, i = m.group(0), rng.randrange(1, len(m.group(0)) - 1)
    kind = rng.choice(("drop", "double", "swap_key"))
    if kind == "drop":
        new = word[:i] + word[i + 1 :]
    elif kind == "double":
        new = word[: i + 1] + word[i] + word[i + 1 :]
    else:
        near = {"a": "s", "e": "r", "i": "o", "o": "p", "n": "m", "t": "y", "r": "t", "l": "k"}
        new = word[:i] + near.get(word[i].lower(), "x") + word[i + 1 :]
    if new.casefold() == word.casefold():
        new = word[:i] + word[i + 1 :]
    return text[: m.start()] + new + text[m.end() :]


def _synonym(text: str) -> str | None:
    out = text
    for plain, other in SYNONYMS:
        out = re.sub(rf"\b{plain}\b", other, out, flags=re.IGNORECASE)
    return out if out != text else None


_STYLE_WEIGHTS: dict[Style, int] = {"question": 4, "terse": 3, "typo": 2, "synonym": 6}


def render(full: str, terse: str, protect: set[str], rng: random.Random) -> tuple[str, Style]:
    """The prompt in a style drawn from the weights among the styles that can apply to its words
    (a synonym needs a word of the table, a typo a plain word to misspell). The synonym weight is
    high because few prompts hold a word of the table."""
    base = rng.choice((full, terse))
    options: dict[Style, str] = {"question": full, "terse": terse}
    if (typed := _typo(base, protect, rng)) is not None:
        options["typo"] = typed
    if (swapped := _synonym(base) or _synonym(full if base == terse else terse)) is not None:
        options["synonym"] = swapped
    style = rng.choices(list(options), weights=[_STYLE_WEIGHTS[k] for k in options])[0]
    return options[style], style


# --- lookup and find -------------------------------------------------------------------------


def _optional(doc: SynthDoc, asked: str | None) -> dict[str, Cons]:
    """The constraints a document can offer beyond its type, left out where the asked field
    itself would give the answer away."""
    out: dict[str, Cons] = {}
    t = doc.doc_type
    person = _constraint_person(doc)
    if person is not None:
        out["person"] = Cons(t, person=person)
    place_names = [v for v in _place_values(doc)]
    if place_names and asked not in PLACE_LIKE:
        out["place"] = Cons(t, place=short_place(place_names[0]))
    if asked not in PRODUCT_LIKE:
        brand = _brand_of(doc)
        if brand:
            out["brand"] = Cons(t, brand=brand)
        if _product_of(doc):
            out["product"] = Cons(t, product=_product_of(doc))
    return out


def _constraint_person(doc: SynthDoc) -> str | None:
    if doc.owner not in (None, "home"):
        return doc.owner
    return doc.linked_people[0] if doc.linked_people else None


def _merge(doc_type: DocType, parts: Iterable[Cons]) -> Cons:
    merged = Cons(doc_type)
    for p in parts:
        merged = Cons(
            doc_type,
            person=p.person or merged.person,
            place=p.place or merged.place,
            brand=p.brand or merged.brand,
            product=p.product or merged.product,
        )
    return merged


def _size(cons: Cons) -> int:
    return sum(x is not None for x in (cons.person, cons.place, cons.brand, cons.product))


def _targets_for(
    doc: SynthDoc,
    docs: Sequence[SynthDoc],
    asked: str | None,
    rng: random.Random,
) -> tuple[Cons, list[SynthDoc]] | None:
    """The smallest constraints that leave every fitting document with the same answer (a find:
    only the document itself), mostly the smallest, sometimes one more for variety."""
    options = _optional(doc, asked)
    names = sorted(options)
    valid: list[tuple[Cons, list[SynthDoc]]] = []
    for size in range(len(names) + 1):
        for combo in itertools.combinations(names, size):
            cons = _merge(doc.doc_type, (options[n] for n in combo))
            found = [d for d in docs if fits(d, cons)]
            if doc not in found:
                continue
            if asked is None:
                ok = len(found) == 1
            else:
                ok = len({json.dumps(truth_value(d, asked)) for d in found}) == 1
            if ok:
                valid.append((cons, found))
    if not valid:
        return None
    sizes = {id(v[0]): _size(v[0]) for v in valid}
    smallest = min(sizes.values())
    wanted = smallest + (1 if rng.random() < 0.35 else 0)
    pool = [v for v in valid if sizes[id(v[0])] == wanted] or [
        v for v in valid if sizes[id(v[0])] == smallest
    ]
    return rng.choice(pool)


def _askable_fields(doc: SynthDoc) -> list[str]:
    names = [
        f
        for f in ASKABLE
        if isinstance(doc.fields.get(f), str)
        and (doc.doc_type, f) not in SECRET
        and f in doc.field_lines
    ]
    if doc.doc_type in STATUS_TYPES and truth_value(doc, STATUS_VALID) is not None:
        names.append(STATUS_VALID)
    if doc.doc_type is DocType.warranty_card and truth_value(doc, STATUS_WARRANTY) is not None:
        names.append(STATUS_WARRANTY)
    return names


def _where(doc: SynthDoc, field_name: str) -> tuple[int | None, Box | None]:
    """The page and box of the truth line that prints the value (for a status, the date line)."""
    source = status_source(doc.doc_type, field_name) or field_name
    idx = doc.field_lines.get(source)
    if not idx:
        return None, None
    line = doc.lines[idx[0]]
    return line.page, line.bbox


def _origin(docs: Iterable[SynthDoc]) -> Origin:
    return "eval-v1" if any(origin_of(d) == "eval-v1" for d in docs) else "extra"


def _ask_text(field_name: str) -> Ask:
    if field_name in ASK:
        return ASK[field_name]
    label = FIELD_LABELS[field_name]
    return _DEFAULT_ASK[0].replace("{label}", label), _DEFAULT_ASK[1].replace("{label}", label)


def _document_question(
    kind: Literal["lookup", "find"],
    doc: SynthDoc,
    docs: Sequence[SynthDoc],
    household: Household,
    split: Split,
    n: int,
    rng: random.Random,
) -> Question | None:
    asked: str | None = None
    if kind == "lookup":
        names = _askable_fields(doc)
        if not names:
            return None
        statuses = [f for f in names if f.startswith("status.")]
        asked = rng.choice(statuses) if statuses and rng.random() < 0.25 else rng.choice(names)
    got = _targets_for(doc, docs, asked, rng)
    if got is None:
        return None
    cons, found = got
    s, sn, protect = _subject(cons, household, rng)
    if asked in PLACE_LIKE and asked and asked in s.casefold():
        return None  # "the hospital on the hospital bill" reads oddly
    if asked is None:
        full, terse = f"Where is {s}?", sn
        full = rng.choice((f"Find {s}", f"Where is {s}?", f"Show me {s}"))
    else:
        full_t, terse_t = _ask_text(asked)
        full, terse = full_t.format(s=s), terse_t.format(sn=sn)
    prompt, style = render(full, terse, protect, rng)
    page = box = None
    value: JsonValue = None
    if asked is not None:
        value = truth_value(found[0], asked)
        page, box = _where(found[0], asked)
    return Question(
        id=f"{split}-{kind}-{n:03d}",
        split=split,
        kind=kind,
        origin=_origin(found),
        style=style,
        prompt=prompt,
        targets=[d.doc_id for d in found],
        field=asked,
        value=value,
        page=page,
        box=box,
    )


def _document_questions(
    kind: Literal["lookup", "find"],
    count: int,
    docs: Sequence[SynthDoc],
    household: Household,
    split: Split,
    seed: int,
) -> list[Question]:
    rng = random.Random(f"{seed}/{split}/{kind}")
    filed = [d for d in docs if is_filed(d)]
    out: list[Question] = []
    seen: set[str] = set()
    for _ in range(3):  # up to three passes, so a document is asked about at most three times
        order = filed[:]
        rng.shuffle(order)
        for doc in order:
            if len(out) >= count:
                return out
            q = _document_question(kind, doc, docs, household, split, len(out) + 1, rng)
            if q is not None and q.prompt not in seen:
                seen.add(q.prompt)
                out.append(q)
    return out


# --- list ------------------------------------------------------------------------------------

_FORWARD_PHRASES = (
    "before March",
    "before June",
    "by December",
    "next 3 months",
    "next 6 months",
    "before January 2027",
    "this year",
    "next month",
)
_PAST_PHRASES = (
    "this year",
    "last year",
    "FY 2025-26",
    "FY 2024-25",
    "in March 2026",
    "last month",
)
_FORWARD_WORD: dict[DateRole, str] = {
    "expiry": "expire",
    "renewal": "are up for renewal",
    "due": "are due",
}


def _say(phrase: str) -> str:
    """A time phrase as a person says it in a sentence ("next 3 months" gets its "in the")."""
    return f"in the {phrase}" if re.match(r"next \d", phrase) else phrase


@dataclass
class _Draft:
    reading: QueryReading
    full: str
    terse: str
    protect: set[str] = field(default_factory=set)


def _reading(
    *,
    people: Sequence[str] = (),
    types: Sequence[DocType] = (),
    areas: Sequence[Area] = (),
    role: DateRole | None = None,
    phrase: str | None = None,
    place: str | None = None,
    intent: Literal["lookup", "list", "find"] = "list",
    words: str = "",
) -> QueryReading:
    return QueryReading(
        intent=intent,
        people=list(people),
        types=list(types),
        areas=list(areas),
        field=None,
        date=DateSlot(role=role, phrase=phrase) if phrase else None,
        place=place,
        words=words,
    )


def _list_drafts(
    docs: Sequence[SynthDoc], household: Household, rng: random.Random
) -> list[_Draft]:
    """Candidate list prompts from templates over people, areas, types, roles, places and
    phrases. Each one is kept only if it finds something in this vault."""
    filed = [d for d in docs if is_filed(d)]
    names = [_first(p.name) for p in household.people]
    drafts: list[_Draft] = []

    def add(reading: QueryReading, full: str, terse: str, protect: Iterable[str] = ()) -> None:
        drafts.append(_Draft(reading, full, terse, {p.casefold() for p in protect}))

    for who, area in itertools.product(names, AREA_PHRASE):
        phrase = AREA_PHRASE[area]
        add(
            _reading(people=[who], areas=[area]),
            rng.choice((f"What {phrase} do we have for {who}?", f"Show me {who}'s {phrase}")),
            f"{who} {phrase}",
            [who],
        )
    for who, (dt, plural) in itertools.product(names, PLURAL.items()):
        add(
            _reading(people=[who], types=[dt]),
            rng.choice((f"Show me {who}'s {plural}", f"List all of {who}'s {plural}")),
            f"{who} {plural}",
            [who],
        )
    for area in AREA_PHRASE:
        for role, word in _FORWARD_WORD.items():
            if area not in (Area.insurance, Area.identity, Area.vehicle, Area.purchases):
                continue
            ph = rng.choice(_FORWARD_PHRASES)
            add(
                _reading(areas=[area], role=role, phrase=ph),
                f"Which {AREA_PHRASE[area]} {word} {_say(ph)}?",
                f"{AREA_PHRASE[area]} {role} {ph}",
            )
    for ph in _FORWARD_PHRASES:
        add(_reading(role="expiry", phrase=ph), f"What expires {_say(ph)}?", f"expiring {ph}")
        add(
            _reading(role="renewal", phrase=ph),
            f"What is up for renewal {_say(ph)}?",
            f"renewals {ph}",
        )
    for who, ph in itertools.product(names, _FORWARD_PHRASES[:6]):
        add(
            _reading(people=[who], areas=[Area.insurance], role="expiry", phrase=ph),
            f"Which of {who}'s insurance papers expire {_say(ph)}?",
            f"{who} insurance expiring {ph}",
            [who],
        )
    for dt, plural in PLURAL.items():
        for ph in _PAST_PHRASES:
            past: DateRole = "purchase" if dt is DocType.tax_invoice else "document"
            if dt is DocType.tax_invoice:
                add(
                    _reading(types=[dt], role=past, phrase=ph),
                    f"{plural.capitalize()} from {ph}",
                    f"{plural} {ph}",
                )
            else:
                add(
                    _reading(types=[dt], role=past, phrase=ph),
                    rng.choice(
                        (f"{plural.capitalize()} for {ph}", f"{plural.capitalize()} from {ph}")
                    ),
                    f"{plural} {ph}",
                )
    seen_places: set[str] = set()
    for d in filed:
        for value in _place_values(d):
            place = short_place(value)
            if place in seen_places or len(place) < 5:
                continue
            seen_places.add(place)
            protect = place.split()
            add(
                _reading(place=place),
                rng.choice((f"Everything from {place}", f"What do we have from {place}?")),
                f"documents {place}",
                protect,
            )
            if d.doc_type is DocType.tax_invoice:
                for ph in ("this year", "last year", "FY 2025-26"):
                    add(
                        _reading(types=[d.doc_type], place=place, role="purchase", phrase=ph),
                        f"Bills from {place} {ph}",
                        f"{place} bills {ph}",
                        protect,
                    )
            if AREA[d.doc_type] is Area.insurance:
                add(
                    _reading(areas=[Area.insurance], place=place),
                    f"Policies from {place}",
                    f"{place} policies",
                    protect,
                )
    for ph in ("this year", "last year", "FY 2025-26"):
        add(
            _reading(areas=[Area.medical], role="document", phrase=ph),
            f"Medical records from {ph}",
            f"medical {ph}",
        )
    for kind, dts in GROUPS.items():
        for who in names:
            add(
                _reading(people=[who], types=list(dts)),
                f"Show me {who}'s {kind}",
                f"{who} {kind}",
                [who],
            )
    return drafts


def _list_questions(
    docs: Sequence[SynthDoc], household: Household, split: Split, today: date, seed: int
) -> list[Question]:
    rng = random.Random(f"{seed}/{split}/list")
    drafts = _list_drafts(docs, household, rng)
    rng.shuffle(drafts)
    out: list[Question] = []
    seen: set[str] = set()
    for draft in drafts:
        if len(out) >= N_LIST:
            break
        query = resolve(draft.reading, household, today)
        if query.unread:
            continue
        expected = apply_query(query, docs)
        if not 1 <= len(expected) <= MAX_LIST_MEMBERS:
            continue
        prompt, style = render(draft.full, draft.terse, draft.protect, rng)
        if prompt in seen:
            continue
        seen.add(prompt)
        by_id = {d.doc_id: d for d in docs}
        out.append(
            Question(
                id=f"{split}-list-{len(out) + 1:03d}",
                split=split,
                kind="list",
                origin=_origin(by_id[i] for i in expected),
                style=style,
                prompt=prompt,
                targets=expected,
                query=query,
                expected=expected,
            )
        )
    return out


# --- none ------------------------------------------------------------------------------------

NOT_HELD_PRODUCTS = (
    "dishwasher",
    "laptop",
    "water purifier",
    "vacuum cleaner",
    "iPhone",
    "geyser",
    "inverter",
    "printer",
)
OUTSIDERS = ("Anil", "Meera", "Rohit", "Sunita", "Girish", "Naveen", "Deepa", "Ramesh")
_PRODUCT_HOMES = (DocType.tax_invoice, DocType.warranty_card)
_OUTSIDER_TYPES = (
    DocType.health_policy,
    DocType.pan,
    DocType.passport,
    DocType.vehicle_policy,
    DocType.payslip,
    DocType.life_policy,
    DocType.driving_licence,
    DocType.prescription,
)


def fits_something(query: Query, docs: Sequence[SynthDoc]) -> bool:
    """Whether any filed document fits a none prompt's query: its people and types as for a list,
    and its words against the product text. A person the household does not hold fits nothing."""
    if any(u.startswith("person:") for u in query.unread):
        return False
    found = set(apply_query(query, docs))
    if not query.words:
        return bool(found)
    words = normalise_name(query.words)
    for d in docs:
        if d.doc_id not in found:
            continue
        text = " ".join(str(d.fields.get(f) or "") for f in ("product", "brand", "model", "seller"))
        if _has_phrase(text, words):
            return True
    return False


def _none_questions(
    docs: Sequence[SynthDoc], household: Household, split: Split, today: date, seed: int
) -> list[Question]:
    rng = random.Random(f"{seed}/{split}/none")
    held = {d.doc_type for d in docs}
    names = [_first(p.name) for p in household.people]
    drafts: list[_Draft] = []

    def add(reading: QueryReading, full: str, terse: str, protect: Iterable[str]) -> None:
        drafts.append(_Draft(reading, full, terse, {p.casefold() for p in protect}))

    for dt in DocType:
        if dt not in held and dt in TYPE_LABELS and dt is not DocType.other:
            label = TYPE_LABELS[dt]
            add(
                _reading(types=[dt], intent="find"),
                f"Find the {label}",
                label,
                [],
            )
    for who, dt in itertools.product(names, PLURAL):
        cons = Cons(dt, person=next(p.id for p in household.people if _first(p.name) == who))
        if not any(fits(d, cons) for d in docs):
            s, sn, protect = _subject(cons, household, rng)
            add(_reading(people=[who], types=[dt], intent="find"), f"Find {s}", sn, protect)
    for product, dt in itertools.product(NOT_HELD_PRODUCTS, _PRODUCT_HOMES):
        noun = "invoice" if dt is DocType.tax_invoice else TYPE_LABELS[dt]
        add(
            _reading(types=[dt], words=product, intent="find"),
            f"Find the {product} {noun}",
            f"{product} {noun}",
            product.split(),
        )
    for who, dt in itertools.product(OUTSIDERS, _OUTSIDER_TYPES):
        noun = TYPE_LABELS[dt]
        add(
            _reading(people=[who], types=[dt], intent="find"),
            f"Find {who}'s {noun}",
            f"{who} {noun}",
            [who],
        )
    rng.shuffle(drafts)
    out: list[Question] = []
    seen: set[str] = set()
    kinds_used: Counter[str] = Counter()
    for draft in drafts:
        if len(out) >= N_NONE:
            break
        query = resolve(draft.reading, household, today)
        # a person the household does not hold must be reported as unread, never matched
        outsider = bool(draft.reading.people) and any(
            match_person(p, household).person_id is None
            and not any(
                normalise_name(p) == normalise_name(_first(x.name)) for x in household.people
            )
            for p in draft.reading.people
        )
        if query.unread and not outsider:
            continue
        if fits_something(query, docs):
            continue
        group = "person" if outsider else "product" if draft.reading.words else "type"
        if kinds_used[group] >= 8:
            continue
        prompt, style = render(draft.full, draft.terse, draft.protect, rng)
        if prompt in seen:
            continue
        seen.add(prompt)
        kinds_used[group] += 1
        out.append(
            Question(
                id=f"{split}-none-{len(out) + 1:03d}",
                split=split,
                kind="none",
                origin="extra",
                style=style,
                prompt=prompt,
                targets=[],
                query=query,
                expected=[],
            )
        )
    return out


# --- the set ---------------------------------------------------------------------------------


def build_questions(
    docs: Sequence[SynthDoc], household: Household, split: Split, today: date, seed: int
) -> list[Question]:
    """Every question of a split: lookups, finds, lists and nones, in that order."""
    return [
        *_document_questions("lookup", N_LOOKUP, docs, household, split, seed),
        *_document_questions("find", N_FIND, docs, household, split, seed),
        *_list_questions(docs, household, split, today, seed),
        *_none_questions(docs, household, split, today, seed),
    ]


def summary(docs: Sequence[SynthDoc], questions: Sequence[Question]) -> dict[str, object]:
    """Counts a results file quotes: documents by origin, the ones left out of questions, and
    questions by kind, style and origin."""
    return {
        "documents": dict(Counter(origin_of(d) for d in docs)),
        "documents_filed": dict(Counter(origin_of(d) for d in docs if is_filed(d))),
        "documents_left_out": dict(Counter(origin_of(d) for d in docs if not is_filed(d))),
        "questions": len(questions),
        "by_kind": dict(Counter(q.kind for q in questions)),
        "by_style": dict(Counter(q.style for q in questions)),
        "by_origin": dict(Counter(q.origin for q in questions)),
        "by_kind_and_origin": dict(Counter(f"{q.kind}/{q.origin}" for q in questions)),
    }


def write_set(out: Path = SEARCH_DIR) -> dict[str, dict[str, object]]:
    household = load_household(EVAL_V1 / "household.json")
    sums: dict[str, dict[str, object]] = {}
    for split in SPLITS:
        docs = search_vault_docs(split)
        questions = build_questions(docs, household, split, EVAL_TODAY, SET_SEED)
        text = "".join(q.model_dump_json() + "\n" for q in questions)
        (out / f"{split}.jsonl").write_text(text)
        sums[split] = summary(docs, questions)
    (out / "summary.json").write_text(json.dumps(sums, indent=2) + "\n")
    return sums


def load_questions(split: Split, folder: Path = SEARCH_DIR) -> list[Question]:
    lines = (folder / f"{split}.jsonl").read_text().splitlines()
    return [Question.model_validate_json(line) for line in lines if line]


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="evals.search_set")
    p.add_argument("--out", type=Path, default=SEARCH_DIR)
    a = p.parse_args(argv)
    print(json.dumps(write_set(a.out), indent=2))


if __name__ == "__main__":
    main()
