from pydantic import BaseModel, Field

from household_vault.schemas._coerce import (
    Address,
    Amount,
    FlexDate,
    Gstin,
    Identifier,
    Name,
    Text,
)


class WarrantyPart(BaseModel):
    part: Text | None = None
    years: Amount | None = None

    def key(self) -> str:
        """Canonical item text, the same shape as the ground truth: 'Magnetron:2'."""
        years = "" if self.years is None else f"{self.years.normalize():f}"
        return f"{self.part or ''}:{years}"


class WarrantyCard(BaseModel):
    brand: Text | None = None
    product: Text | None = None
    model: Identifier | None = None
    serial_number: Identifier | None = None
    purchase_date: FlexDate | None = None
    seller: Text | None = None
    seller_location: Address | None = Field(
        default=None, description="city of the store, or the online platform"
    )
    buyer: Name | None = None
    warranty_parts: list[WarrantyPart] | None = None


class TaxInvoice(BaseModel):
    seller: Text | None = None
    seller_location: Address | None = Field(
        default=None, description="city of the store, or the online platform"
    )
    buyer: Name | None = None
    gstin: Gstin | None = None
    invoice_number: Identifier | None = None
    invoice_date: FlexDate | None = None
    product: Text | None = None
    model: Identifier | None = None
    serial_number: Identifier | None = None
    amount: Amount | None = None


class Purchase(BaseModel):
    """Extended warranties, annual maintenance contracts and appliance service records."""

    brand: Text | None = None
    product: Text | None = None
    model: Identifier | None = None
    serial_number: Identifier | None = None
    seller: Text | None = None
    seller_location: Address | None = Field(
        default=None, description="city of the store, or the online platform"
    )
    order_id: Identifier | None = None
    buyer: Name | None = None
    purchase_date: FlexDate | None = None
    amount: Amount | None = None
    invoice_number: Identifier | None = None
    period_start: FlexDate | None = None
    period_end: FlexDate | None = None
    visits: Amount | None = None
    service_helpline: Identifier | None = None
