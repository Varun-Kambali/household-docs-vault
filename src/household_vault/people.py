"""The household file: who lives here, and the other ways their names are printed."""

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class PersonEntry(BaseModel):
    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)


class Household(BaseModel):
    people: list[PersonEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ids_are_unique(self) -> "Household":
        seen: set[str] = set()
        for person in self.people:
            if person.id in seen:
                raise ValueError(f"two people share the id {person.id!r}")
            seen.add(person.id)
        return self

    def by_id(self, person_id: str) -> PersonEntry:
        for person in self.people:
            if person.id == person_id:
                return person
        raise KeyError(person_id)


def load_household(path: Path) -> Household:
    """A missing file is an empty household; a file that does not parse raises."""
    if not path.exists():
        return Household()
    return Household.model_validate_json(path.read_text(encoding="utf-8"))


PERSON_MIN = 0.8
_HONORIFICS = frozenset({"mr", "mrs", "ms", "miss", "dr", "shri", "smt", "sri", "kumari", "master"})


def normalise_name(name: str) -> str:
    """Casefolded, honorifics dropped, punctuation turned into spaces, spaces collapsed."""
    words = re.sub(r"[\W_]+", " ", unicodedata.normalize("NFKC", name).casefold()).split()
    return " ".join(w for w in words if w not in _HONORIFICS)


@dataclass(frozen=True)
class PersonMatch:
    """`person_id` is set only when one person is the clear best match; `candidates` lists
    everyone tied at the best score (two or more) when it is not."""

    person_id: str | None
    score: float
    candidates: tuple[str, ...] = ()


def _is_subsequence(short: list[str], long: list[str]) -> bool:
    it = iter(long)
    return all(token in it for token in short)


def _fits_a_middle(token: str, middles: set[str]) -> bool:
    return any(token == m or (len(token) == 1 and m.startswith(token)) for m in middles)


def _score(printed: list[str], known: list[str], middles: set[str]) -> float:
    """`middles` holds every middle name the person has under any of their names; a printed
    middle name that is none of them is a different person's name, not a missing middle."""
    if not printed or not known:
        return 0.0
    if printed == known:
        return 1.0
    if sorted(printed) == sorted(known):
        return 0.9
    if (
        len(printed) >= 2
        and len(known) >= 2
        and printed[0] == known[0]
        and printed[-1] == known[-1]
    ):
        short, long = sorted((printed[1:-1], known[1:-1]), key=len)
        conflict = bool(middles) and not all(_fits_a_middle(t, middles) for t in printed[1:-1])
        if _is_subsequence(short, long) and not conflict:
            return 0.9
    # earlier tokens line up left to right; the known name may have extra middle tokens
    earlier = zip(printed[:-1], known[:-1], strict=False)
    if (
        printed[-1] == known[-1]
        and 1 <= len(printed) - 1 <= len(known) - 1
        and all(p == k or (len(p) == 1 and k.startswith(p)) for p, k in earlier)
    ):
        return 0.8
    return 0.0


def match_person(name: str, household: Household) -> PersonMatch:
    """Who a printed name belongs to. A tie at the best score between two people is not a
    match: the caller has to ask."""
    printed = normalise_name(name).split()
    best = 0.0
    scores: dict[str, float] = {}
    for person in household.people:
        names = [normalise_name(n).split() for n in (person.name, *person.aliases)]
        middles = {t for tokens in names for t in tokens[1:-1]}
        top = max((_score(printed, tokens, middles) for tokens in names), default=0.0)
        scores[person.id] = top
        best = max(best, top)
    if best < PERSON_MIN:
        return PersonMatch(None, best)
    tied = tuple(pid for pid, s in scores.items() if s == best)
    if len(tied) == 1:
        return PersonMatch(tied[0], best)
    return PersonMatch(None, best, tied)
