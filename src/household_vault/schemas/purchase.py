from pydantic import BaseModel

from household_vault.schemas._coerce import Amount, FlexDate, Text


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
    model: Text | None = None
    serial_number: Text | None = None
    purchase_date: FlexDate | None = None
    seller: Text | None = None
    seller_location: Text | None = None
    warranty_parts: list[WarrantyPart] | None = None


class TaxInvoice(BaseModel):
    seller: Text | None = None
    seller_location: Text | None = None
    gstin: Text | None = None
    invoice_number: Text | None = None
    invoice_date: FlexDate | None = None
    product: Text | None = None
    model: Text | None = None
    serial_number: Text | None = None
    amount: Amount | None = None
