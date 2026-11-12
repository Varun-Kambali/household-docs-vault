from pydantic import BaseModel

from household_vault.schemas._coerce import FlexDate, Text


class Aadhaar(BaseModel):
    holder: Text | None = None
    date_of_birth: FlexDate | None = None
    address: Text | None = None
    number: Text | None = None


class Pan(BaseModel):
    number: Text | None = None
    holder: Text | None = None
    father_name: Text | None = None
    date_of_birth: FlexDate | None = None
