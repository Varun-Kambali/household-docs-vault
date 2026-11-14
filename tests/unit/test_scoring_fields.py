from datetime import date
from decimal import Decimal

from household_vault.schemas import HealthPolicy, Prescription, WarrantyCard
from household_vault.schemas.medical import Medicine
from household_vault.schemas.purchase import WarrantyPart
from household_vault.scoring import normalise, score_fields


def test_normalisers_per_kind():
    assert normalise("identifier", "P/12 3456-7") == normalise("identifier", "p/1234567")
    assert normalise("aadhaar", "2345 6789-0123") == "234567890123"
    assert normalise("gstin", "29abcde 1234f1z5") == "29abcde1234f1z5"
    assert normalise("address", "No. 4, Temple Road") == normalise("address", "No. 4 Temple Road")
    assert normalise("address", "A,  B") == "a b"
    assert normalise("name", "Dr. Ravi  Rao") == normalise("name", "dr ravi rao")
    assert normalise("text", "Rao, Ravi") != normalise("text", "Rao Ravi")
    assert normalise("text", "Rao,  RAVI") == "rao, ravi"


def test_a_filled_unprinted_field_is_a_false_positive():
    s = score_fields(
        HealthPolicy,
        {"policy_number": "P1", "nominee": None},
        HealthPolicy(policy_number="P1", nominee="Somebody"),
    )
    assert s.exact == {"policy_number": True} and (s.tp, s.fp, s.fn) == (1, 1, 0)


def test_wrong_and_missing_values():
    truth = {"policy_number": "P1", "insurer": "Acme", "nominee": "Asha"}
    got = HealthPolicy(policy_number="P2", insurer=None, nominee="asha")
    s = score_fields(HealthPolicy, truth, got)
    assert s.exact == {"policy_number": False, "insurer": False, "nominee": True}
    assert (s.tp, s.fp, s.fn) == (1, 1, 2)


def test_dates_and_amounts_compare_by_value():
    truth = {"end_date": "18/01/2027", "premium": "Rs. 28,910"}
    got = HealthPolicy(end_date=date(2027, 1, 18), premium=Decimal("28910.00"))
    assert score_fields(HealthPolicy, truth, got).exact == {"end_date": True, "premium": True}


def test_lists_compare_as_multisets_of_item_keys():
    truth = {"insured": "Asha; Ravi", "medicines": "Cetirizine 10 mg 1-1-1 5 days"}
    rx = Prescription(
        medicines=[Medicine(name="Cetirizine", dose="10 mg", timing="1-1-1", duration="5 days")]
    )
    assert score_fields(Prescription, {"medicines": truth["medicines"]}, rx).exact == {
        "medicines": True
    }
    pol = HealthPolicy(insured=["ravi", "Asha"])
    assert score_fields(HealthPolicy, {"insured": truth["insured"]}, pol).exact == {"insured": True}
    dup = HealthPolicy(insured=["Asha", "Asha"])
    assert score_fields(HealthPolicy, {"insured": truth["insured"]}, dup).exact == {
        "insured": False
    }


def test_warranty_parts_use_their_key():
    card = WarrantyCard(warranty_parts=[WarrantyPart(part="Magnetron", years=Decimal("2"))])
    assert score_fields(WarrantyCard, {"warranty_parts": "Magnetron:2"}, card).exact == {
        "warranty_parts": True
    }
