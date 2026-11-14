from pydantic import BaseModel, Field

from household_vault.schemas._coerce import (
    Amount,
    CardNumber,
    Cvv,
    FlexDate,
    Identifier,
    Name,
    Text,
)


class CardFront(BaseModel):
    bank: Text | None = None
    card_name: Text | None = None
    number: CardNumber | None = None
    expiry: Text | None = Field(default=None, description="as printed, month and year")
    holder: Name | None = None
    network: Text | None = None
    cvv: Cvv | None = Field(default=None, description="on the back of the card")


class CardDoc(BaseModel):
    """Card statements and welcome letters, which print only the last four digits."""

    bank: Text | None = None
    card_name: Text | None = None
    network: Text | None = None
    holder: Name | None = None
    last4: Identifier | None = None
    statement_date: FlexDate | None = None
    payment_due_date: FlexDate | None = None
    total_due: Amount | None = None
    credit_limit: Amount | None = None
    annual_fee: Amount | None = None
