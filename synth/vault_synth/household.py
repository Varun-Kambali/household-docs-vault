"""The fictional household every eval document is written about, and who a page names.

All four people are invented. Their aliases are the other ways a page might print the name, so
the app has to match "Mrs Kavita Rao" and "KAVITA RAO" to the same person.
"""

import random
from dataclasses import dataclass

from faker import Faker

from household_vault.people import Household, PersonEntry
from household_vault.reasons import Reason
from vault_synth.sets import SetSpec

HOUSEHOLD = Household(
    people=[
        PersonEntry(
            id="p1",
            name="Ravi Kumar Rao",
            aliases=["RAVI KUMAR RAO", "Ravi K Rao", "R K Rao", "Ravi Rao"],
        ),
        PersonEntry(
            id="p2", name="Kavita Rao", aliases=["KAVITA RAO", "Kavita R Rao", "Mrs Kavita Rao"]
        ),
        PersonEntry(id="p3", name="Kiran Rao", aliases=["KIRAN RAO", "Master Kiran Rao"]),
        PersonEntry(id="p4", name="Suresh Rao", aliases=["SURESH N RAO", "S N Rao"]),
    ]
)
# Initials that fit both p2 (Kavita) and p3 (Kiran): the app has to ask which one.
AMBIGUOUS = "K Rao"

_MALE_IDS = {"p1", "p3", "p4"}
_KANNADA = {
    "ravi": "ರವಿ",
    "kumar": "ಕುಮಾರ್",
    "kavita": "ಕವಿತಾ",
    "kiran": "ಕಿರಣ್",
    "suresh": "ಸುರೇಶ್",
    "rao": "ರಾವ್",
}


@dataclass(frozen=True)
class CastMember:
    """One name printed on a page: who it is (None for an outsider or an unclear name)."""

    person_id: str | None
    printed: str


def _known_words() -> set[str]:
    words: set[str] = set()
    for p in HOUSEHOLD.people:
        for name in (p.name, *p.aliases):
            words.update(w.lower() for w in name.split())
    return words


def _outsider_name(rng: random.Random) -> str:
    fake = Faker("en_IN")
    fake.seed_instance(rng.randrange(2**31))
    known = _known_words()
    while True:
        name = str(fake.name())
        # no word of a fake name may match the household, or a rule could not call it foreign
        if not known & {w.lower() for w in name.split()}:
            return name


def draw_cast(
    rng: random.Random, spec: SetSpec, n_people: int
) -> tuple[list[CastMember], list[Reason]]:
    """Pick the names a page prints, each in one of the person's printed forms."""
    chosen = rng.sample(HOUSEHOLD.people, n_people)
    cast = [CastMember(p.id, rng.choice([p.name, *p.aliases])) for p in chosen]
    reasons: list[Reason] = []
    if rng.random() < spec.outsider_rate:
        cast[0] = CastMember(None, _outsider_name(rng))
        reasons.append(Reason.person_unknown)
    elif rng.random() < spec.ambiguous_rate:
        cast[0] = CastMember(None, AMBIGUOUS)
        reasons.append(Reason.person_unsure)
    return cast, reasons


def is_male(member: CastMember, rng: random.Random) -> bool:
    if member.person_id is None:
        return rng.random() < 0.5
    return member.person_id in _MALE_IDS


def kannada_name(printed: str) -> str | None:
    """The name in Kannada script, or None when a word is not one the household uses."""
    words = [w.lower() for w in printed.split()]
    if not words or any(w not in _KANNADA for w in words):
        return None
    return " ".join(_KANNADA[w] for w in words)
