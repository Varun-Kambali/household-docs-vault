"""What the app extracts from each document type. Every field is optional: a page that does not
print a field leaves it empty."""

from pydantic import BaseModel

from household_vault.doctypes import DocType
from household_vault.schemas.card import CardFront
from household_vault.schemas.identity import Aadhaar, Pan
from household_vault.schemas.insurance import HealthPolicy, VehiclePolicy
from household_vault.schemas.medical import LabReport, LabTest, Medicine, Prescription
from household_vault.schemas.purchase import TaxInvoice, WarrantyCard, WarrantyPart

SCHEMAS: dict[DocType, type[BaseModel]] = {
    DocType.health_policy: HealthPolicy,
    DocType.vehicle_policy: VehiclePolicy,
    DocType.warranty_card: WarrantyCard,
    DocType.tax_invoice: TaxInvoice,
    DocType.aadhaar: Aadhaar,
    DocType.pan: Pan,
    DocType.card_front: CardFront,
    DocType.prescription: Prescription,
    DocType.lab_report: LabReport,
}

__all__ = [
    "SCHEMAS",
    "Aadhaar",
    "CardFront",
    "HealthPolicy",
    "LabReport",
    "LabTest",
    "Medicine",
    "Pan",
    "Prescription",
    "TaxInvoice",
    "VehiclePolicy",
    "WarrantyCard",
    "WarrantyPart",
]
