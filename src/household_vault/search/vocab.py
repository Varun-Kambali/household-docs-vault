"""The words search knows: what to call each type, area and field, which date field plays which
role for a type, and which fields name a place or are worth showing in a finder row.

The reading model for a prompt sees only these words, never a document, so every name here is
the fixed vocabulary it can ask for.
"""

from collections.abc import Collection
from typing import Literal, cast

from household_vault.doctypes import AREA, Area, DocType

_D = DocType

TYPE_LABELS: dict[DocType, str] = {
    _D.life_policy: "life insurance policy",
    _D.health_policy: "health insurance policy",
    _D.vehicle_policy: "vehicle insurance policy",
    _D.home_policy: "home insurance policy",
    _D.travel_policy: "travel insurance policy",
    _D.gadget_policy: "gadget insurance policy",
    _D.accident_policy: "accident insurance policy",
    _D.tax_invoice: "purchase invoice",
    _D.warranty_card: "warranty card",
    _D.extended_warranty: "extended warranty",
    _D.amc: "annual maintenance contract",
    _D.appliance_service_record: "appliance service record",
    _D.aadhaar: "Aadhaar card",
    _D.pan: "PAN card",
    _D.passport: "passport",
    _D.voter_id: "voter ID",
    _D.driving_licence: "driving licence",
    _D.birth_certificate: "birth certificate",
    _D.marriage_certificate: "marriage certificate",
    _D.sale_deed: "sale deed",
    _D.rent_agreement: "rent agreement",
    _D.khata: "khata",
    _D.property_tax_receipt: "property tax receipt",
    _D.encumbrance_certificate: "encumbrance certificate",
    _D.utility_bill: "utility bill",
    _D.registration_certificate: "vehicle registration certificate",
    _D.puc_certificate: "pollution certificate",
    _D.fastag: "FASTag",
    _D.vehicle_service_record: "vehicle service record",
    _D.payslip: "payslip",
    _D.offer_letter: "offer letter",
    _D.appointment_letter: "appointment letter",
    _D.appraisal_letter: "appraisal letter",
    _D.relieving_letter: "relieving letter",
    _D.experience_letter: "experience letter",
    _D.certificate: "certificate",
    _D.marksheet: "marksheet",
    _D.degree: "degree certificate",
    _D.form_16: "Form 16",
    _D.itr_acknowledgement: "income tax return acknowledgement",
    _D.tax_proof: "tax saving proof",
    _D.card_front: "card",
    _D.card_statement: "card statement",
    _D.card_welcome_letter: "card welcome letter",
    _D.prescription: "prescription",
    _D.lab_report: "lab report",
    _D.scan_photo: "scan image",
    _D.scan_report: "scan report",
    _D.discharge_summary: "discharge summary",
    _D.hospital_bill: "hospital bill",
    _D.visit_recording: "doctor visit recording",
    _D.other: "other document",
}

# Words a person types for a type, besides its label. A product is text in an invoice, so
# "fridge bill" is not listed: it is a bill (invoice) with "fridge" as its product.
TYPE_WORDS: dict[DocType, tuple[str, ...]] = {
    _D.life_policy: ("life insurance", "term plan", "term insurance", "lic"),
    _D.health_policy: ("mediclaim", "health insurance", "medical insurance"),
    _D.vehicle_policy: (
        "car insurance",
        "bike insurance",
        "motor insurance",
        "two wheeler insurance",
    ),
    _D.home_policy: ("home insurance", "house insurance", "property insurance"),
    _D.travel_policy: ("travel insurance",),
    _D.gadget_policy: ("phone insurance", "mobile insurance", "gadget insurance"),
    _D.accident_policy: ("personal accident cover", "accident insurance"),
    _D.tax_invoice: ("bill", "invoice", "receipt", "purchase bill"),
    _D.warranty_card: ("warranty", "guarantee card"),
    _D.extended_warranty: ("extended warranty", "protection plan"),
    _D.amc: ("amc", "maintenance contract", "service contract"),
    _D.appliance_service_record: ("service report", "service record", "repair record"),
    _D.aadhaar: ("aadhar", "aadhaar", "uid"),
    _D.pan: ("pan", "permanent account number"),
    _D.passport: ("passport",),
    _D.voter_id: ("voter card", "epic", "election card"),
    _D.driving_licence: ("dl", "driving license", "licence"),
    _D.birth_certificate: ("birth certificate",),
    _D.marriage_certificate: ("marriage certificate",),
    _D.sale_deed: ("deed", "sale deed", "property papers"),
    _D.rent_agreement: ("lease", "rental agreement", "rent agreement"),
    _D.khata: ("khata", "khata certificate", "khata extract"),
    _D.property_tax_receipt: ("property tax", "house tax", "bbmp receipt"),
    _D.encumbrance_certificate: ("ec", "encumbrance"),
    _D.utility_bill: ("electricity bill", "water bill", "gas bill", "broadband bill", "bescom"),
    _D.registration_certificate: ("rc", "rc book", "vehicle registration"),
    _D.puc_certificate: ("puc", "pollution check", "emission certificate"),
    _D.fastag: ("fastag", "toll tag"),
    _D.vehicle_service_record: ("car service", "bike service", "vehicle service"),
    _D.payslip: ("salary slip", "pay slip", "payslip"),
    _D.offer_letter: ("job offer", "offer letter"),
    _D.appointment_letter: ("appointment letter", "joining letter"),
    _D.appraisal_letter: ("appraisal", "hike letter", "increment letter"),
    _D.relieving_letter: ("relieving letter", "resignation acceptance"),
    _D.experience_letter: ("experience letter", "experience certificate"),
    _D.certificate: ("certificate", "course certificate"),
    _D.marksheet: ("marks card", "marksheet", "mark sheet", "report card"),
    _D.degree: ("degree", "convocation certificate"),
    _D.form_16: ("form 16", "form16", "tds certificate"),
    _D.itr_acknowledgement: ("itr", "tax return", "itr v", "income tax return"),
    _D.tax_proof: ("80c", "tax proof", "investment proof", "tax saving"),
    _D.card_front: ("credit card", "debit card", "card"),
    _D.card_statement: ("card statement", "credit card bill", "credit card statement"),
    _D.card_welcome_letter: ("card welcome kit", "card welcome letter"),
    _D.prescription: ("prescription", "medicines list", "rx"),
    _D.lab_report: ("blood test", "lab report", "test report", "pathology report"),
    _D.scan_photo: ("scan image", "x-ray", "mri", "ct scan"),
    _D.scan_report: ("scan report", "radiology report", "ultrasound report"),
    _D.discharge_summary: ("discharge summary", "discharge papers"),
    _D.hospital_bill: ("hospital bill", "hospital invoice", "medical bill"),
    _D.visit_recording: ("doctor recording", "visit recording"),
}

# Words that go with a type name without naming a type ("policy", "documents"); they are
# dropped from a phrase before it is tested as a person or a place.
GENERIC_WORDS: frozenset[str] = frozenset(
    {"policy", "policies", "insurance", "document", "documents", "papers", "paper"}
)

_AREA_NAMES: dict[Area, str] = {
    Area.insurance: "insurance",
    Area.purchases: "purchases",
    Area.identity: "identity",
    Area.vehicle: "vehicle",
    Area.work: "work",
    Area.education: "education",
    Area.tax: "tax",
    Area.cards: "cards",
    Area.medical: "medical",
    Area.property: "property",
    Area.rent: "rent",
    Area.utilities: "utilities",
}
AREA_LABELS: dict[Area, str] = dict(_AREA_NAMES)

# Every field of every schema is askable, so each has a plain label. The label is also the
# word indexed in front of the field's value.
FIELD_LABELS: dict[str, str] = {
    "insurer": "insurer",
    "product": "product",
    "policy_number": "policy number",
    "policyholder": "policyholder",
    "insured": "insured person",
    "nominee": "nominee",
    "sum_insured": "sum insured",
    "premium": "premium",
    "premium_frequency": "premium frequency",
    "start_date": "start date",
    "end_date": "end date",
    "premium_due_date": "premium due date",
    "agent": "agent",
    "claim_helpline": "claim helpline",
    "registration_number": "registration number",
    "idv": "insured declared value",
    "ncb_percent": "no claim bonus percent",
    "seller": "seller",
    "seller_location": "seller location",
    "buyer": "buyer",
    "gstin": "GSTIN",
    "invoice_number": "invoice number",
    "invoice_date": "invoice date",
    "model": "model",
    "serial_number": "serial number",
    "amount": "amount",
    "brand": "brand",
    "purchase_date": "purchase date",
    "warranty_parts": "warranty parts",
    "order_id": "order ID",
    "period_start": "period start",
    "period_end": "period end",
    "visits": "visits",
    "service_helpline": "service helpline",
    "holder": "holder",
    "date_of_birth": "date of birth",
    "address": "address",
    "number": "number",
    "father_name": "father name",
    "issue_date": "issue date",
    "expiry_date": "expiry date",
    "parties": "parties",
    "person_name": "person name",
    "document_date": "document date",
    "certificate_number": "certificate number",
    "tag_id": "tag ID",
    "odometer_km": "odometer km",
    "employer": "employer",
    "net_pay": "net pay",
    "designation": "designation",
    "issuer": "issuer",
    "credential_id": "credential ID",
    "roll_number": "roll number",
    "assessment_year": "assessment year",
    "acknowledgement_number": "acknowledgement number",
    "section": "section",
    "bank": "bank",
    "card_name": "card name",
    "expiry": "expiry",
    "network": "network",
    "cvv": "CVV",
    "last4": "last four digits",
    "statement_date": "statement date",
    "payment_due_date": "payment due date",
    "total_due": "total due",
    "credit_limit": "credit limit",
    "annual_fee": "annual fee",
    "hospital": "hospital",
    "doctor": "doctor",
    "patient": "patient",
    "date": "date",
    "medicines": "medicines",
    "next_visit": "next visit",
    "lab": "lab",
    "tests": "tests",
    "department": "department",
    "diagnoses": "diagnoses",
    "procedures": "procedures",
    "allergies": "allergies",
    "khata_number": "khata number",
    "receipt_number": "receipt number",
    "rent_amount": "rent amount",
    "deposit": "deposit",
    "provider": "provider",
    "consumer_number": "consumer number",
}

DateRole = Literal["expiry", "renewal", "due", "purchase", "issue", "document"]

_POLICIES = (
    _D.life_policy,
    _D.health_policy,
    _D.vehicle_policy,
    _D.home_policy,
    _D.travel_policy,
    _D.gadget_policy,
    _D.accident_policy,
)
_PURCHASE_PERIODS = (_D.extended_warranty, _D.amc, _D.appliance_service_record)
_IDENTITY_DATED = (
    _D.passport,
    _D.voter_id,
    _D.driving_licence,
    _D.birth_certificate,
    _D.marriage_certificate,
)
_MEDICAL_DATED = (
    _D.prescription,
    _D.lab_report,
    _D.scan_photo,
    _D.scan_report,
    _D.discharge_summary,
    _D.hospital_bill,
)

_LIGHT_AREAS = {
    Area.property,
    Area.rent,
    Area.utilities,
    Area.vehicle,
    Area.work,
    Area.education,
    Area.tax,
}


def _put(roles: dict[DateRole, str], **fields: str) -> None:
    roles.update(cast(dict[DateRole, str], fields))


def _roles() -> dict[DocType, dict[DateRole, str]]:
    roles: dict[DocType, dict[DateRole, str]] = {t: {"document": "doc_date"} for t in DocType}
    for t in _POLICIES:
        _put(
            roles[t],
            expiry="end_date",
            renewal="end_date",
            due="premium_due_date",
            purchase="start_date",
            issue="start_date",
        )
    _put(roles[_D.tax_invoice], purchase="invoice_date", issue="invoice_date")
    _put(roles[_D.warranty_card], purchase="purchase_date", issue="purchase_date")
    for t in _PURCHASE_PERIODS:
        _put(
            roles[t],
            purchase="purchase_date",
            issue="period_start",
            expiry="period_end",
            renewal="period_end",
        )
    for t in _IDENTITY_DATED:
        _put(roles[t], issue="issue_date", expiry="expiry_date", renewal="expiry_date")
    for t in AREA:
        if AREA[t] in _LIGHT_AREAS:
            _put(
                roles[t],
                issue="document_date",
                expiry="expiry_date",
                renewal="expiry_date",
                due="expiry_date",
            )
    for t in (_D.card_statement, _D.card_welcome_letter):
        _put(roles[t], issue="statement_date", due="payment_due_date")
    for t in _MEDICAL_DATED:
        _put(roles[t], issue="date", due="next_visit")
    roles[_D.lab_report].pop("due", None)
    return roles


# The role of a date field, to that type's field. `document` is the row's own date column.
DATE_ROLES: dict[DocType, dict[DateRole, str]] = _roles()

# Date fields that play no role in a "before" or "expires" question.
ROLELESS_DATES: dict[DocType, frozenset[str]] = {
    **{t: frozenset() for t in DocType},
    **{t: frozenset({"date_of_birth"}) for t in (_D.aadhaar, _D.pan, *_IDENTITY_DATED)},
}

# Fields that name where a thing came from.
PLACE_FIELDS: dict[DocType, tuple[str, ...]] = {
    **{t: () for t in DocType},
    **{t: ("insurer",) for t in _POLICIES},
    _D.tax_invoice: ("seller",),
    _D.warranty_card: ("seller",),
    **{t: ("seller",) for t in _PURCHASE_PERIODS},
    _D.card_front: ("bank",),
    _D.card_statement: ("bank",),
    _D.card_welcome_letter: ("bank",),
    _D.prescription: ("hospital",),
    _D.lab_report: ("lab",),
    _D.scan_photo: ("hospital",),
    _D.scan_report: ("hospital",),
    _D.discharge_summary: ("hospital",),
    _D.hospital_bill: ("hospital",),
    _D.utility_bill: ("provider",),
    **{
        t: ("employer",)
        for t in (
            _D.payslip,
            _D.offer_letter,
            _D.appointment_letter,
            _D.appraisal_letter,
            _D.relieving_letter,
            _D.experience_letter,
            _D.form_16,
        )
    },
    **{t: ("issuer",) for t in (_D.certificate, _D.marksheet, _D.degree)},
}

# Two or three fields a finder row shows under the file name.
KEY_FIELDS: dict[DocType, tuple[str, ...]] = {
    **{t: ("insurer", "policy_number", "end_date") for t in _POLICIES},
    _D.vehicle_policy: ("insurer", "registration_number", "end_date"),
    _D.tax_invoice: ("seller", "product", "amount"),
    _D.warranty_card: ("brand", "product", "serial_number"),
    **{t: ("brand", "product", "period_end") for t in _PURCHASE_PERIODS},
    _D.aadhaar: ("holder", "number"),
    _D.pan: ("holder", "number"),
    **{t: ("holder", "number", "expiry_date") for t in _IDENTITY_DATED},
    _D.registration_certificate: ("registration_number", "person_name"),
    _D.puc_certificate: ("registration_number", "expiry_date"),
    _D.fastag: ("registration_number", "tag_id"),
    _D.vehicle_service_record: ("registration_number", "odometer_km"),
    _D.sale_deed: ("person_name", "registration_number"),
    _D.rent_agreement: ("person_name", "rent_amount"),
    _D.khata: ("person_name", "khata_number"),
    _D.property_tax_receipt: ("person_name", "amount"),
    _D.encumbrance_certificate: ("person_name", "certificate_number"),
    _D.utility_bill: ("provider", "consumer_number"),
    _D.payslip: ("employer", "net_pay"),
    **{
        t: ("employer", "designation")
        for t in (
            _D.offer_letter,
            _D.appointment_letter,
            _D.appraisal_letter,
            _D.relieving_letter,
            _D.experience_letter,
        )
    },
    _D.certificate: ("issuer", "credential_id"),
    _D.marksheet: ("issuer", "roll_number"),
    _D.degree: ("issuer", "roll_number"),
    _D.form_16: ("employer", "assessment_year"),
    _D.itr_acknowledgement: ("assessment_year", "acknowledgement_number"),
    _D.tax_proof: ("section", "amount"),
    _D.card_front: ("bank", "card_name", "holder"),
    _D.card_statement: ("bank", "last4", "payment_due_date"),
    _D.card_welcome_letter: ("bank", "last4", "card_name"),
    _D.prescription: ("doctor", "hospital", "medicines"),
    _D.lab_report: ("lab", "tests"),
    _D.scan_photo: ("patient", "hospital", "department"),
    _D.scan_report: ("patient", "hospital", "department"),
    _D.discharge_summary: ("patient", "hospital", "diagnoses"),
    _D.hospital_bill: ("patient", "hospital", "amount"),
    _D.visit_recording: ("patient", "doctor"),
    _D.other: ("patient", "doctor"),
}

# ID numbers a finder row shows as the last four digits until the owner taps them.
MASKED_FIELDS: frozenset[tuple[DocType, str]] = frozenset(
    (t, "number") for t in (_D.aadhaar, _D.pan, _D.passport, _D.voter_id, _D.driving_licence)
)


# A question names a field by what people say ("expiry date", "number"), which is not always the
# name a type stores it under. `field_for` maps an asked name to the type's own: first the date
# fields by role, then the type's main identifier and main person name.
# The plain "number" a person asks for. A specific kind (an invoice number, a serial number, a
# registration number) is a different thing and is never mapped to another type's identifier.
_ID_FIELDS = frozenset({"number", "policy_number", "certificate_number", "last4"})
_NAME_FIELDS = frozenset({"holder", "policyholder", "insured", "person_name", "patient"})

PRIMARY_ID: dict[DocType, str] = {
    **{t: "policy_number" for t in _POLICIES},
    _D.tax_invoice: "invoice_number",
    _D.warranty_card: "serial_number",
    **{t: "number" for t in (_D.aadhaar, _D.pan, _D.card_front, *_IDENTITY_DATED)},
    _D.registration_certificate: "registration_number",
    _D.sale_deed: "registration_number",
    _D.puc_certificate: "certificate_number",
    _D.encumbrance_certificate: "certificate_number",
    _D.fastag: "tag_id",
    _D.khata: "khata_number",
    _D.property_tax_receipt: "receipt_number",
    _D.utility_bill: "consumer_number",
    _D.certificate: "credential_id",
    _D.marksheet: "roll_number",
    _D.degree: "roll_number",
    _D.itr_acknowledgement: "acknowledgement_number",
    _D.card_statement: "last4",
    _D.card_welcome_letter: "last4",
}
PRIMARY_NAME: dict[DocType, str] = {
    **{t: "policyholder" for t in _POLICIES},
    **{
        t: "holder"
        for t in (_D.aadhaar, _D.pan, _D.card_front, _D.card_statement, _D.card_welcome_letter)
    },
    **{t: "holder" for t in _IDENTITY_DATED},
    **{t: "patient" for t in (*_MEDICAL_DATED, _D.scan_photo)},
    **{t: "person_name" for t in AREA if AREA[t] in _LIGHT_AREAS},
}

_ROLE_ORDER: tuple[DateRole, ...] = ("expiry", "renewal", "due", "purchase", "issue")


def field_for(doc_type: DocType, asked: str, stored: Collection[str]) -> str | None:
    """The name this type stores what `asked` names under, or None. A name the type holds is
    returned as it is. `stored` is the type's field names."""
    if asked in stored:
        return asked
    roles = {r for per_type in DATE_ROLES.values() for r, f in per_type.items() if f == asked}
    own = DATE_ROLES[doc_type]
    for role in _ROLE_ORDER:
        if role in roles and own.get(role) in stored:
            return own[role]
    table = PRIMARY_ID if asked in _ID_FIELDS else PRIMARY_NAME if asked in _NAME_FIELDS else {}
    target = table.get(doc_type)
    return target if target in stored else None
