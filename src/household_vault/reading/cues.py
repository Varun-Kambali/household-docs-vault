"""Title phrases that say what a page is, used to check the model's type answer.

A cue is a lowercase phrase from a form title, a hand-drawn template title or common real
wording. The check never decides the type; it tells the caller when the model and the page's own
words disagree, so the document can be held for a look.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from household_vault.doctypes import DocType

_D = DocType

TYPE_CUES: dict[DocType, tuple[str, ...]] = {
    _D.life_policy: ("life insurance policy schedule", "life insurance", "life assured"),
    _D.health_policy: ("health insurance - policy schedule", "health insurance", "mediclaim"),
    _D.vehicle_policy: (
        "private car package policy",
        "certificate cum policy schedule",
        "motor insurance",
        "two wheeler package policy",
    ),
    _D.home_policy: ("home insurance policy schedule", "home insurance", "householder"),
    _D.travel_policy: ("travel insurance certificate", "travel insurance"),
    _D.gadget_policy: ("mobile and gadget protection plan", "gadget protection"),
    _D.accident_policy: ("personal accident insurance schedule", "personal accident"),
    _D.tax_invoice: ("tax invoice",),
    _D.warranty_card: ("warranty card",),
    _D.extended_warranty: ("extended warranty certificate", "extended warranty"),
    _D.amc: ("annual maintenance contract", "maintenance contract"),
    _D.appliance_service_record: ("appliance service",),
    _D.aadhaar: ("unique identification authority", "aadhaar"),
    _D.pan: ("income tax department", "permanent account number"),
    _D.passport: ("passport",),
    _D.voter_id: ("elector photo identity card", "election commission"),
    _D.driving_licence: ("driving licence", "driving license"),
    _D.birth_certificate: ("certificate of birth", "birth certificate"),
    _D.marriage_certificate: ("certificate of registration of marriage", "marriage certificate"),
    _D.sale_deed: ("sale deed",),
    _D.rent_agreement: ("rental agreement", "rent agreement"),
    _D.khata: ("khata certificate", "khata"),
    _D.property_tax_receipt: ("property tax receipt", "property tax"),
    _D.encumbrance_certificate: ("encumbrance certificate",),
    _D.utility_bill: ("electricity bill", "water bill"),
    _D.registration_certificate: ("registration certificate",),
    _D.puc_certificate: ("pollution under control certificate", "pollution under control"),
    _D.fastag: ("fastag issuance details", "fastag"),
    _D.vehicle_service_record: ("vehicle service invoice", "vehicle service"),
    _D.payslip: ("payslip", "pay slip", "salary slip"),
    _D.offer_letter: ("offer letter",),
    _D.appointment_letter: ("letter of appointment", "appointment letter"),
    _D.appraisal_letter: ("annual appraisal letter", "appraisal letter"),
    _D.relieving_letter: ("relieving letter",),
    _D.experience_letter: ("experience certificate", "experience letter"),
    _D.certificate: (
        "certificate of completion",
        "certificate of achievement",
        "certificate of participation",
    ),
    _D.marksheet: ("statement of marks", "marksheet", "mark sheet"),
    _D.degree: ("degree certificate",),
    _D.form_16: ("form no. 16", "form 16"),
    _D.itr_acknowledgement: ("income tax return acknowledgement", "itr-v"),
    _D.tax_proof: ("investment proof",),
    _D.card_front: ("valid thru", "valid through"),
    _D.card_statement: ("credit card statement", "card statement"),
    _D.card_welcome_letter: ("welcome to your new card",),
    _D.prescription: ("rx",),
    _D.lab_report: ("laboratory report", "lab report"),
    _D.scan_photo: ("ultrasound images", "ultrasound"),
    _D.scan_report: ("radiology report", "mri report"),
    _D.discharge_summary: ("discharge summary",),
    _D.hospital_bill: ("hospital bill",),
}

# Phrases printed on pages of several types. Finding one is never proof of a type: it makes the
# check silent. The stand-in models use them only when no specific cue is found.
GENERIC_CUES: dict[str, DocType] = {
    "policy schedule": _D.health_policy,
    "reference range": _D.lab_report,
    "test report": _D.lab_report,
    "service report": _D.appliance_service_record,
    "service record": _D.appliance_service_record,
    "prescription": _D.prescription,
    "certificate of registration": _D.registration_certificate,
    "final bill": _D.hospital_bill,
}


@dataclass(frozen=True)
class CueCheck:
    verdict: Literal["agrees", "silent", "conflicts"]
    other: DocType | None = None


def _found(cue: str, text: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(cue)}(?![a-z0-9])", text) is not None


def _longest(text: str, *, skip: DocType | None = None) -> tuple[DocType | None, int]:
    """The type with the longest specific cue found in lowercased text (the first listed wins a
    tie), and that cue's length."""
    best: DocType | None = None
    best_len = 0
    for doc_type, cues in TYPE_CUES.items():
        if doc_type is skip:
            continue
        for cue in cues:
            if len(cue) > best_len and _found(cue, text):
                best, best_len = doc_type, len(cue)
    return best, best_len


def best_cue_match(text: str) -> DocType | None:
    """The type the page's words point to: the longest specific cue, else a generic phrase."""
    low = text.lower()
    best, _ = _longest(low)
    if best is not None:
        return best
    for phrase, doc_type in GENERIC_CUES.items():
        if _found(phrase, low):
            return doc_type
    return None


def cue_check(text: str, doc_type: DocType) -> CueCheck:
    """agrees: the claimed type's best cue is at least as long as any other type's; conflicts:
    another type's cue is longer (or the claimed type has none) and names that type; silent:
    no specific cue at all, so only generic phrases or nothing."""
    low = text.lower()
    mine = max((len(c) for c in TYPE_CUES.get(doc_type, ()) if _found(c, low)), default=0)
    other, other_len = _longest(low, skip=doc_type)
    if other is not None and other_len > mine:
        return CueCheck("conflicts", other)
    return CueCheck("agrees") if mine else CueCheck("silent")
