from household_vault.doctypes import AREA, Area, DocType
from household_vault.schemas import SCHEMAS
from household_vault.schemas._coerce import field_kind
from household_vault.search.vocab import (
    AREA_LABELS,
    DATE_ROLES,
    FIELD_LABELS,
    KEY_FIELDS,
    MASKED_FIELDS,
    PLACE_FIELDS,
    ROLELESS_DATES,
    TYPE_LABELS,
    TYPE_WORDS,
)


def test_every_field_has_a_label_and_every_date_field_a_role_or_a_reason():
    for doc_type, schema in SCHEMAS.items():
        for name in schema.model_fields:
            assert name in FIELD_LABELS
            if field_kind(schema, name) == "date":
                assert name in DATE_ROLES[doc_type].values() or name in ROLELESS_DATES[doc_type]


def test_every_type_and_area_has_a_label():
    assert set(TYPE_LABELS) == set(DocType)
    assert set(AREA_LABELS) == set(Area)
    assert TYPE_LABELS[DocType.health_policy] == "health insurance policy"
    assert set(TYPE_WORDS) <= set(DocType)


def test_roles_places_and_key_fields_name_real_fields():
    for doc_type, schema in SCHEMAS.items():
        names = set(schema.model_fields)
        for field in DATE_ROLES[doc_type].values():
            assert field in names or field == "doc_date"
        assert DATE_ROLES[doc_type]["document"] == "doc_date"
        assert set(ROLELESS_DATES[doc_type]) <= names
        assert set(PLACE_FIELDS[doc_type]) <= names
        assert set(KEY_FIELDS[doc_type]) <= names
        assert 2 <= len(KEY_FIELDS[doc_type]) <= 3


def test_masked_fields_are_the_id_numbers():
    assert {t for t, _ in MASKED_FIELDS} == {
        DocType.aadhaar,
        DocType.pan,
        DocType.passport,
        DocType.voter_id,
        DocType.driving_licence,
    }
    assert {f for _, f in MASKED_FIELDS} == {"number"}
    assert all(AREA[t] is Area.identity for t, _ in MASKED_FIELDS)
