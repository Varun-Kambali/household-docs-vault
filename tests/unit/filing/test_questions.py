import pytest
from vault_synth.household import HOUSEHOLD

from household_vault.doctypes import DocType
from household_vault.filing.questions import question_for
from household_vault.reading.cues import CueCheck
from household_vault.reasons import PRIORITY, Reason
from tests.conftest import reading_of

PEOPLE = ["Ravi Kumar Rao", "Kavita Rao", "Kiran Rao", "Suresh Rao", "Home"]


def test_one_question_by_priority():
    q = question_for(
        [Reason.possible_copy, Reason.person_unknown],
        reading_of(DocType.prescription),
        HOUSEHOLD,
        {},
    )
    assert q.reason is Reason.person_unknown
    assert q.text == "Prescription with no name I know on it. Whose is it?"
    assert [o.label for o in q.options] == PEOPLE
    assert [o.value for o in q.options] == ["p1", "p2", "p3", "p4", "home"]
    assert q.answer_kind == "person"


def test_nothing_to_ask_is_an_error():
    with pytest.raises(ValueError):
        question_for([], None, HOUSEHOLD, {})


def test_an_unsure_name_offers_the_candidates_first():
    q = question_for(
        [Reason.person_unsure], reading_of(DocType.pan), HOUSEHOLD, {"printed": "K Rao"}
    )
    assert q.text == 'PAN card for "K Rao". Is it Kavita Rao or Kiran Rao?'
    assert [o.label for o in q.options] == [
        "Kavita Rao",
        "Kiran Rao",
        "Ravi Kumar Rao",
        "Suresh Rao",
        "Home",
    ]


def test_type_questions():
    conflict = reading_of(DocType.aadhaar, type_check=CueCheck("conflicts", DocType.tax_invoice))
    q = question_for([Reason.type_unsure], conflict, HOUSEHOLD, {})
    assert q.text == "Is this an Aadhaar or an invoice?"
    assert q.answer_kind == "type"
    assert [o.value for o in q.options[:2]] == ["aadhaar", "tax_invoice"]
    assert "other" not in [o.value for o in q.options]
    assert "visit_recording" not in [o.value for o in q.options]
    q = question_for([Reason.type_unsure], reading_of(DocType.other), HOUSEHOLD, {})
    assert q.text == "What kind of document is this?"
    q = question_for([Reason.no_english], reading_of(None), HOUSEHOLD, {})
    assert q.text == "This page has no English I can read. What kind of document is it?"
    assert q.answer_kind == "type"


def test_field_questions_name_the_field_from_the_reading_or_the_context():
    pan = reading_of(DocType.pan, holder="Ravi Rao", number=None)
    q = question_for([Reason.missing_required], pan, HOUSEHOLD, {})
    assert q.text == "I could not read the number on this PAN card. What is it?"
    assert (q.answer_kind, q.field, q.options) == ("field", "number", [])
    policy = reading_of(DocType.health_policy, policy_number=None, end_date=None)
    q = question_for([Reason.missing_required], policy, HOUSEHOLD, {"field": "end_date"})
    assert q.text == "I could not read the end date on this health policy. What is it?"
    issue = reading_of(DocType.pan, holder="Ravi Rao", number=None, issues={"number": "bad"})
    q = question_for([Reason.field_issue], issue, HOUSEHOLD, {})
    assert q.text == "The number on this PAN card is not something I can use. What is it?"
    assert q.field == "number"


def test_copy_questions():
    ctx = {"path": "Ravi Kumar Rao/Insurance/x.pdf", "date": "2026-11-01"}
    q = question_for([Reason.possible_copy], None, HOUSEHOLD, ctx)
    assert q.text == (
        "This looks like Ravi Kumar Rao/Insurance/x.pdf, filed on 2026-11-01. "
        "Keep both, or discard this one?"
    )
    assert [o.value for o in q.options] == ["keep_both", "discard"] and q.answer_kind == "copy"
    q = question_for([Reason.duplicate], None, HOUSEHOLD, ctx)
    assert q.text == (
        "This is the same file as Ravi Kumar Rao/Insurance/x.pdf. Discard this copy, or keep both?"
    )
    assert [o.value for o in q.options] == ["discard", "keep_both"]


@pytest.mark.parametrize(
    ("reason", "text", "kind"),
    [
        (Reason.locked, "This PDF is locked. Unlock it with its password to read it.", "unlock"),
        (
            Reason.recording,
            "Visit recordings are filed by the medical step, which comes later. "
            "Leave it here for now.",
            "retry",
        ),
        (
            Reason.copy_mismatch,
            "The copy I made of this file did not match it, twice. Try again?",
            "retry",
        ),
        (
            Reason.card_unreadable,
            "I could not read this card's number. Upload a clearer photo in the app, "
            "then discard this one.",
            "discard",
        ),
    ],
)
def test_fixed_questions(reason, text, kind):
    q = question_for([reason], None, HOUSEHOLD, {})
    assert (q.text, q.answer_kind) == (text, kind)


def test_unreadable_files_say_why():
    q = question_for([Reason.damaged], None, HOUSEHOLD, {"why": "it is damaged"})
    assert (
        q.text
        == "I cannot read this file (it is damaged). Discard it, or drop a PDF or a photo instead."
    )
    assert q.answer_kind == "discard"
    for reason in (Reason.unsupported_type, Reason.empty_file):
        assert (
            question_for([reason], None, HOUSEHOLD, {"why": "it is empty"}).answer_kind == "discard"
        )


def test_a_failed_read_offers_a_retry_or_a_type():
    q = question_for([Reason.read_failed], None, HOUSEHOLD, {})
    assert q.text == "I could not read this document. Try again, or tell me what it is."
    assert q.answer_kind == "retry" and q.options[0].value == "retry"
    assert DocType.pan.value in [o.value for o in q.options]


def test_every_reason_has_a_question_with_no_emoji_or_dash():
    for reason in PRIORITY:
        q = question_for([reason], reading_of(DocType.pan), HOUSEHOLD, {"printed": "K Rao"})
        assert q.reason is reason and q.text
        assert q.text.isascii() and "—" not in q.text


_AN = {
    DocType.accident_policy,
    DocType.tax_invoice,
    DocType.extended_warranty,
    DocType.aadhaar,
    DocType.encumbrance_certificate,
    DocType.registration_certificate,
    DocType.offer_letter,
    DocType.appointment_letter,
    DocType.appraisal_letter,
    DocType.experience_letter,
    DocType.itr_acknowledgement,
}


def test_every_label_gets_its_article():
    from household_vault.doctypes import LABEL

    for t in LABEL:
        if t in (DocType.pan, DocType.other):
            continue
        r = reading_of(t, type_check=CueCheck("conflicts", DocType.pan))
        text = question_for([Reason.type_unsure], r, HOUSEHOLD, {}).text
        article = "an" if t in _AN else "a"
        assert text.startswith(f"Is this {article} "), text
        assert text.endswith(" or a PAN card?"), text
    r = reading_of(DocType.pan, type_check=CueCheck("conflicts", DocType.fastag))
    assert question_for([Reason.type_unsure], r, HOUSEHOLD, {}).text == (
        "Is this a PAN card or a FASTag?"
    )
    r = reading_of(DocType.utility_bill, type_check=CueCheck("conflicts", DocType.form_16))
    assert question_for([Reason.type_unsure], r, HOUSEHOLD, {}).text == (
        "Is this a utility bill or a Form 16?"
    )


def test_other_is_never_offered_as_an_answer():
    r = reading_of(DocType.other)
    options = question_for([Reason.type_unsure], r, HOUSEHOLD, {}).options
    assert "other" not in [o.value for o in options]


def test_a_reading_typed_other_never_offers_other_even_when_the_page_names_a_type():
    r = reading_of(DocType.other, type_check=CueCheck("conflicts", DocType.tax_proof))
    q = question_for([Reason.type_unsure], r, HOUSEHOLD, {})
    assert q.text == "What kind of document is this?"
    assert "other" not in [o.value for o in q.options]
    assert "tax_proof" in [o.value for o in q.options]


def test_one_name_read_that_matches_one_person_is_not_called_unknown():
    r = reading_of(DocType.marriage_certificate, parties=["Ravi Rao"])
    q = question_for([Reason.person_unsure], r, HOUSEHOLD, {"printed": "Ravi Rao"})
    assert q.reason is Reason.person_unsure
    assert q.text == 'Marriage certificate for "Ravi Rao". Whose is it?'
    assert q.options[0].value == "p1"


def test_a_lone_card_back_asks_for_the_front_and_back_together():
    q = question_for([Reason.card_unreadable], None, HOUSEHOLD, {"why": "back_only"})
    assert q.text == (
        "This looks like the back of a card. "
        "Upload the front and back together in the app, then discard this one."
    )
    assert q.answer_kind == "discard"
