from pydantic import BaseModel

from household_vault.schemas._coerce import AadhaarNumber, Address, FlexDate, Identifier, Name


class IdentityDoc(BaseModel):
    """Passport, voter ID, driving licence, birth and marriage certificates."""

    holder: Name | None = None
    number: Identifier | None = None
    date_of_birth: FlexDate | None = None
    issue_date: FlexDate | None = None
    expiry_date: FlexDate | None = None
    address: Address | None = None
    parties: list[str] | None = None


class Aadhaar(BaseModel):
    holder: Name | None = None
    date_of_birth: FlexDate | None = None
    address: Address | None = None
    number: AadhaarNumber | None = None


class Pan(BaseModel):
    number: Identifier | None = None
    holder: Name | None = None
    father_name: Name | None = None
    date_of_birth: FlexDate | None = None
