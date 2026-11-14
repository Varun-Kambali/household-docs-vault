"""The household file: who lives here, and the other ways their names are printed."""

from pathlib import Path

from pydantic import BaseModel, Field


class PersonEntry(BaseModel):
    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)


class Household(BaseModel):
    people: list[PersonEntry] = Field(default_factory=list)

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
