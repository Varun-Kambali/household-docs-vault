"""What the app extracts from each document type. Every field is optional: a page that does not
print a field leaves it empty."""

from pydantic import BaseModel

from household_vault.doctypes import AREA, DocType
from household_vault.schemas.card import CardDoc, CardFront
from household_vault.schemas.identity import Aadhaar, IdentityDoc, Pan
from household_vault.schemas.insurance import HealthPolicy, Policy, VehiclePolicy
from household_vault.schemas.light import light_schema
from household_vault.schemas.medical import (
    LabReport,
    LabTest,
    MedicalDoc,
    Medicine,
    Prescription,
)
from household_vault.schemas.purchase import Purchase, TaxInvoice, WarrantyCard, WarrantyPart


def _schema_for(doc_type: DocType) -> type[BaseModel]:
    match doc_type:
        case DocType.vehicle_policy:
            return VehiclePolicy
        case DocType.health_policy:
            return HealthPolicy
        case DocType.tax_invoice:
            return TaxInvoice
        case DocType.warranty_card:
            return WarrantyCard
        case DocType.extended_warranty | DocType.amc | DocType.appliance_service_record:
            return Purchase
        case DocType.aadhaar:
            return Aadhaar
        case DocType.pan:
            return Pan
        case DocType.card_front:
            return CardFront
        case DocType.card_statement | DocType.card_welcome_letter:
            return CardDoc
        case DocType.prescription:
            return Prescription
        case DocType.lab_report:
            return LabReport
        case (
            DocType.scan_photo
            | DocType.scan_report
            | DocType.discharge_summary
            | DocType.hospital_bill
        ):
            return MedicalDoc
    if doc_type in (
        DocType.life_policy,
        DocType.home_policy,
        DocType.travel_policy,
        DocType.gadget_policy,
        DocType.accident_policy,
    ):
        return Policy
    if doc_type in (
        DocType.passport,
        DocType.voter_id,
        DocType.driving_licence,
        DocType.birth_certificate,
        DocType.marriage_certificate,
    ):
        return IdentityDoc
    return light_schema(doc_type)


# Every type the reader fills in: all but `other` and the visit recording (audio, not a page).
SCHEMAS: dict[DocType, type[BaseModel]] = {
    t: _schema_for(t) for t in AREA if t is not DocType.visit_recording
}

__all__ = [
    "SCHEMAS",
    "Aadhaar",
    "CardDoc",
    "CardFront",
    "HealthPolicy",
    "IdentityDoc",
    "LabReport",
    "LabTest",
    "MedicalDoc",
    "Medicine",
    "Pan",
    "Policy",
    "Prescription",
    "Purchase",
    "TaxInvoice",
    "VehiclePolicy",
    "WarrantyCard",
    "WarrantyPart",
    "light_schema",
]
