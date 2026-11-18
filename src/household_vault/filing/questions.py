"""The one question to ask about a held document. The wording is the owner's copy; keep it."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from household_vault.doctypes import LABEL, DocType
from household_vault.filing.decide import required_problems
from household_vault.people import Household, match_person
from household_vault.reading.pipeline import Reading
from household_vault.reasons import PRIORITY, Reason

AnswerKind = Literal["person", "type", "field", "copy", "unlock", "retry", "discard"]

_KEEP_CAPS = frozenset({"Aadhaar", "Form 16"})  # a name, so it keeps its capital mid-sentence
_AN = frozenset(
    {
        DocType.accident_policy,
        DocType.tax_invoice,
        DocType.extended_warranty,
        DocType.aadhaar,
        DocType.encumbrance_certificate,
        DocType.registration_certificate,
        DocType.offer_letter,
        DocType.appointment_letter,
        DocType.appraisal_letter,
        DocType.experience_letter,
        DocType.itr_acknowledgement,
    }
)
# The article for each label, as it is read aloud: "an RC", "a FASTag", "an ITR acknowledgement".
ARTICLE: dict[DocType, str] = {t: "an" if t in _AN else "a" for t in LABEL}


@dataclass(frozen=True)
class Option:
    value: str
    label: str


@dataclass(frozen=True)
class Question:
    reason: Reason
    text: str
    answer_kind: AnswerKind
    options: list[Option]
    field: str | None = None


UPLOAD_AGAIN = "The photo of this card was not kept, so I cannot read it again. Upload it again."


def upload_again_question() -> Question:
    """For an upload that was stopped: its photos were only ever in memory."""
    return Question(Reason.read_failed, UPLOAD_AGAIN, "discard", [Option("discard", "Discard")])


def _label(reading: Reading | None) -> str:
    doc_type = reading.doc_type if reading else None
    return LABEL.get(doc_type, "Document") if doc_type else "Document"


def _mid(label: str) -> str:
    """The label inside a sentence: lower-cased, unless it is a name or an acronym."""
    if label in _KEEP_CAPS or any(c.isupper() for c in label[1:]):
        return label
    return label[:1].lower() + label[1:]


def _a(doc_type: DocType) -> str:
    return f"{ARTICLE[doc_type]} {_mid(LABEL[doc_type])}"


def _people(household: Household, first: Sequence[str] = ()) -> list[Option]:
    ordered = [p for pid in first for p in household.people if p.id == pid]
    ordered += [p for p in household.people if p.id not in first]
    return [Option(p.id, p.name) for p in ordered] + [Option("home", "Home")]


def _types(first: Sequence[DocType] = ()) -> list[Option]:
    rest = [t for t in LABEL if t not in first and t is not DocType.visit_recording]
    return [Option(t.value, LABEL[t]) for t in (*first, *rest)]


def _field_text(name: str) -> str:
    return name.replace("_", " ")


def _problem_field(reason: Reason, reading: Reading | None, context: Mapping[str, str]) -> str:
    if "field" in context:
        return context["field"]
    if reading is not None and reading.doc_type is not None:
        missing, with_issue = required_problems(
            reading.doc_type, reading.fields, reading.issues, reading.secret_values
        )
        names = missing if reason is Reason.missing_required else with_issue
        if names:
            return names[0]
    return "field"


def question_for(
    reasons: Sequence[Reason],
    reading: Reading | None,
    household: Household,
    context: Mapping[str, str],
) -> Question:
    """The question for the first reason in `PRIORITY` order. `context` carries the blanks:
    `printed`, `path`, `date`, `why` and `field`."""
    reason = next((r for r in PRIORITY if r in reasons), None)
    if reason is None:
        raise ValueError("there is nothing to ask")
    label = _label(reading)
    path = context.get("path", "another file")
    match reason:
        case Reason.person_unknown:
            text = f"{label} with no name I know on it. Whose is it?"
            return Question(reason, text, "person", _people(household))
        case Reason.person_unsure:
            printed = context.get("printed", "")
            ids = match_person(printed, household).candidates
            if len(ids) < 2:
                text = f"{label} with no name I know on it. Whose is it?"
                return Question(Reason.person_unknown, text, "person", _people(household))
            names = [household.by_id(i).name for i in ids]
            either = f"{', '.join(names[:-1])} or {names[-1]}"
            text = f'{label} for "{printed}". Is it {either}?'
            return Question(reason, text, "person", _people(household, ids))
        case Reason.type_unsure | Reason.no_english:
            check = reading.type_check if reading else None
            if (
                reason is Reason.type_unsure
                and reading is not None
                and reading.doc_type is not None
                and check is not None
                and check.verdict == "conflicts"
                and check.other is not None
            ):
                pair = (reading.doc_type, check.other)
                text = f"Is this {_a(pair[0])} or {_a(pair[1])}?"
                return Question(reason, text, "type", _types(pair))
            text = (
                "This page has no English I can read. What kind of document is it?"
                if reason is Reason.no_english
                else "What kind of document is this?"
            )
            return Question(reason, text, "type", _types())
        case Reason.missing_required | Reason.field_issue:
            name = _problem_field(reason, reading, context)
            field_label = _field_text(name)
            doc = _mid(label)
            if reason is Reason.missing_required:
                text = f"I could not read the {field_label} on this {doc}. What is it?"
            else:
                text = f"The {field_label} on this {doc} is not something I can use. What is it?"
            return Question(reason, text, "field", [], name)
        case Reason.possible_copy:
            text = (
                f"This looks like {path}, filed on {context.get('date', '')}. "
                "Keep both, or discard this one?"
            )
            options = [Option("keep_both", "Keep both"), Option("discard", "Discard this one")]
            return Question(reason, text, "copy", options)
        case Reason.duplicate:
            text = f"This is the same file as {path}. Discard this copy, or keep both?"
            options = [Option("discard", "Discard this copy"), Option("keep_both", "Keep both")]
            return Question(reason, text, "copy", options)
        case Reason.locked:
            text = "This PDF is locked. Unlock it with its password to read it."
            return Question(reason, text, "unlock", [Option("unlock", "Unlock")])
        case Reason.unsupported_type | Reason.empty_file | Reason.damaged:
            why = context.get("why", "it is damaged")
            text = f"I cannot read this file ({why}). Discard it, or drop a PDF or a photo instead."
            return Question(reason, text, "discard", [Option("discard", "Discard")])
        case Reason.recording:
            text = (
                "Visit recordings are filed by the medical step, which comes later. "
                "Leave it here for now."
            )
            return Question(reason, text, "retry", [Option("retry", "Leave it")])
        case Reason.copy_mismatch:
            text = "The copy I made of this file did not match it, twice. Try again?"
            return Question(reason, text, "retry", [Option("retry", "Try again")])
        case Reason.read_failed:
            text = "I could not read this document. Try again, or tell me what it is."
            return Question(reason, text, "retry", [Option("retry", "Try again"), *_types()])
        case Reason.card_unreadable:
            if context.get("why") == "tilted":
                text = "Take a straighter photo of the card."
                return Question(reason, text, "discard", [Option("discard", "Discard")])
            text = (
                "I could not read this card's number. "
                "Upload a clearer photo in the app, then discard this one."
            )
            return Question(reason, text, "discard", [Option("discard", "Discard")])
    raise ValueError(f"no question for {reason}")  # pragma: no cover
