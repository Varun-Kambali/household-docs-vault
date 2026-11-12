from pydantic import BaseModel, Field

from household_vault.schemas._coerce import Text


class CardFront(BaseModel):
    bank: Text | None = None
    number: Text | None = None
    expiry: Text | None = Field(default=None, description="as printed, month and year")
    holder: Text | None = None
    network: Text | None = None
