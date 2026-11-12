"""Every document type the app reads in v1 (design 5.3). Values are stored in the database."""

from enum import StrEnum


class DocType(StrEnum):
    # Insurance
    life_policy = "life_policy"
    health_policy = "health_policy"
    vehicle_policy = "vehicle_policy"
    home_policy = "home_policy"
    travel_policy = "travel_policy"
    gadget_policy = "gadget_policy"
    accident_policy = "accident_policy"
    # Purchases
    tax_invoice = "tax_invoice"
    warranty_card = "warranty_card"
    extended_warranty = "extended_warranty"
    amc = "amc"
    service_record = "service_record"
    # Identity
    aadhaar = "aadhaar"
    pan = "pan"
    passport = "passport"
    voter_id = "voter_id"
    driving_licence = "driving_licence"
    birth_certificate = "birth_certificate"
    marriage_certificate = "marriage_certificate"
    # Home
    sale_deed = "sale_deed"
    rent_agreement = "rent_agreement"
    khata = "khata"
    property_tax_receipt = "property_tax_receipt"
    encumbrance_certificate = "encumbrance_certificate"
    utility_bill = "utility_bill"
    # Vehicle
    registration_certificate = "registration_certificate"
    puc_certificate = "puc_certificate"
    fastag = "fastag"
    # Work and education
    payslip = "payslip"
    offer_letter = "offer_letter"
    appointment_letter = "appointment_letter"
    appraisal_letter = "appraisal_letter"
    relieving_letter = "relieving_letter"
    experience_letter = "experience_letter"
    certificate = "certificate"
    marksheet = "marksheet"
    degree = "degree"
    # Tax
    form_16 = "form_16"
    itr_acknowledgement = "itr_acknowledgement"
    tax_proof = "tax_proof"
    # Cards
    card_front = "card_front"
    card_statement = "card_statement"
    card_welcome_letter = "card_welcome_letter"
    # Medical
    prescription = "prescription"
    lab_report = "lab_report"
    scan_photo = "scan_photo"
    scan_report = "scan_report"
    discharge_summary = "discharge_summary"
    hospital_bill = "hospital_bill"
    visit_recording = "visit_recording"
    # Anything the router cannot place
    other = "other"
