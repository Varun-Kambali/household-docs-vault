from pydantic import BaseModel

from household_vault.schemas._coerce import Address, Amount, FlexDate, Gstin, Identifier, Text


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
    seller_location: Address | None = None
    warranty_parts: list[WarrantyPart] | None = None


class TaxInvoice(BaseModel):
    seller: Text | None = None
    seller_location: Address | None = None
    gstin: Gstin | None = None
    invoice_number: Identifier | None = None
    invoice_date: FlexDate | None = None
    product: Text | None = None
    model: Identifier | None = None
    serial_number: Identifier | None = None
    amount: Amount | None = None
