from pydantic import BaseModel, Field

from household_vault.schemas._coerce import CardNumber, Cvv, Name, Text


class CardFront(BaseModel):
    bank: Text | None = None
    number: CardNumber | None = None
    expiry: Text | None = Field(default=None, description="as printed, month and year")
    holder: Name | None = None
    network: Text | None = None
    cvv: Cvv | None = Field(default=None, description="on the back of the card")
