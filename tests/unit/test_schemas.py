import typing
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from household_vault.doctypes import DocType
from household_vault.schemas import SCHEMAS, HealthPolicy, Prescription, VehiclePolicy
from household_vault.schemas._coerce import Kind, NameItem, TextItem


def test_schema_fields_match_generator_keys(spike_docs_all):
    for d in spike_docs_all:
        assert set(d.fields) <= set(SCHEMAS[d.doc_type].model_fields)


def test_every_schema_belongs_to_a_known_doc_type():
    assert set(SCHEMAS) <= set(DocType)


def test_all_fields_are_optional():
    for schema in SCHEMAS.values():
        assert schema.model_validate({}) is not None


def test_dates_and_amounts_are_typed():
    p = HealthPolicy.model_validate(
        {"end_date": "18/01/2027", "sum_insured": "Rs. 5,00,000", "premium": "28910"}
    )
    assert p.end_date == date(2027, 1, 18)
    assert p.sum_insured == Decimal(500000)
    assert p.premium == Decimal(28910)


def test_bad_date_is_rejected():
    with pytest.raises(ValidationError):
        HealthPolicy.model_validate({"end_date": "next spring"})


def test_insured_is_a_list_and_medicines_are_objects():
    assert HealthPolicy.model_validate({"insured": ["A", "B"]}).insured == ["A", "B"]
    rx = Prescription.model_validate(
        {
            "medicines": [
                {"name": "Cetirizine", "dose": "10 mg", "timing": "1-1-1", "duration": "5 days"}
            ]
        }
    )
    assert rx.medicines is not None and rx.medicines[0].name == "Cetirizine"


def test_vehicle_policy_percent_is_decimal():
    assert VehiclePolicy.model_validate({"ncb_percent": "20%"}).ncb_percent == Decimal(20)


def test_list_of_names_is_read_like_a_name_field():
    from household_vault.schemas import IdentityDoc, MedicalDoc
    from household_vault.schemas._coerce import field_kind

    assert HealthPolicy.model_fields["insured"].annotation == list[NameItem] | None
    assert field_kind(HealthPolicy, "insured") == "list"
    assert HealthPolicy.model_validate({"insured": ["A B"]}).insured == ["A B"]
    assert IdentityDoc.model_fields["parties"].annotation == list[NameItem] | None
    assert MedicalDoc.model_fields["allergies"].annotation == list[TextItem] | None
    for bad in ([1], [None], [["x"]]):
        with pytest.raises(ValidationError):
            HealthPolicy.model_validate({"insured": bad})
    assert typing.get_args(NameItem)[2] == Kind("name")
    assert typing.get_args(TextItem)[2] == Kind("text")
