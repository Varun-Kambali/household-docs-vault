from pydantic import BaseModel

from household_vault.schemas._coerce import Text


class CardFront(BaseModel):
    bank: Text | None = None
    number: Text | None = None
    expiry: Text | None = None
    holder: Text | None = None
    network: Text | None = None
