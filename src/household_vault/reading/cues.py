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
    _D.life_policy: ("life insurance", "life assured", "term plan"),
    _D.health_policy: ("health insurance", "mediclaim", "policy schedule"),
    _D.vehicle_policy: (
        "private car package policy",
        "certificate cum policy schedule",
        "motor insurance",
        "two wheeler package policy",
    ),
    _D.home_policy: ("home insurance", "householder"),
    _D.travel_policy: ("travel insurance",),
    _D.gadget_policy: ("gadget protection", "mobile protection"),
    _D.accident_policy: ("personal accident",),
    _D.tax_invoice: ("tax invoice",),
    _D.warranty_card: ("warranty card",),
    _D.extended_warranty: ("extended warranty",),
    _D.amc: ("annual maintenance contract", "maintenance contract"),
    _D.appliance_service_record: ("service report", "service record"),
    _D.aadhaar: ("unique identification authority", "aadhaar"),
    _D.pan: ("income tax department", "permanent account number"),
    _D.passport: ("passport",),
    _D.voter_id: ("elector photo identity card", "election commission"),
    _D.driving_licence: ("driving licence", "driving license"),
    _D.birth_certificate: ("certificate of birth", "birth certificate"),
    _D.marriage_certificate: ("certificate of registration of marriage", "marriage certificate"),
    _D.sale_deed: ("sale deed",),
    _D.rent_agreement: ("rental agreement", "rent agreement"),
    _D.khata: ("khata",),
    _D.property_tax_receipt: ("property tax",),
    _D.encumbrance_certificate: ("encumbrance certificate",),
    _D.utility_bill: ("electricity bill", "water bill"),
    _D.registration_certificate: ("certificate of registration", "registration certificate"),
    _D.puc_certificate: ("pollution under control",),
    _D.fastag: ("fastag",),
    _D.vehicle_service_record: ("vehicle service invoice", "vehicle service"),
    _D.payslip: ("payslip", "pay slip", "salary slip"),
    _D.offer_letter: ("offer letter",),
    _D.appointment_letter: ("letter of appointment", "appointment letter"),
    _D.appraisal_letter: ("appraisal letter",),
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
    _D.prescription: ("rx", "prescription"),
    _D.lab_report: ("laboratory report", "lab report", "test report", "reference range"),
    _D.scan_photo: ("ultrasound",),
    _D.scan_report: ("radiology report", "mri report"),
    _D.discharge_summary: ("discharge summary",),
    _D.hospital_bill: ("final bill", "hospital bill"),
}


@dataclass(frozen=True)
class CueCheck:
    verdict: Literal["agrees", "silent", "conflicts"]
    other: DocType | None = None


def _found(cue: str, text: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(cue)}(?![a-z0-9])", text) is not None


def best_cue_match(text: str, *, skip: DocType | None = None) -> DocType | None:
    """The type with the longest cue found in text (the first listed wins a tie)."""
    low = text.lower()
    best: DocType | None = None
    best_len = 0
    for doc_type, cues in TYPE_CUES.items():
        if doc_type is skip:
            continue
        for cue in cues:
            if len(cue) > best_len and _found(cue, low):
                best, best_len = doc_type, len(cue)
    return best


def cue_check(text: str, doc_type: DocType) -> CueCheck:
    low = text.lower()
    if any(_found(c, low) for c in TYPE_CUES.get(doc_type, ())):
        return CueCheck("agrees")
    other = best_cue_match(text, skip=doc_type)
    return CueCheck("conflicts", other) if other else CueCheck("silent")
