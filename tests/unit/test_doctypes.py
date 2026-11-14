from household_vault.doctypes import (
    AREA,
    AREA_FOLDER,
    COPY_KEY,
    CORE,
    DATE_FIELD,
    LABEL,
    LIGHT,
    OWNER,
    REQUIRED,
    SUBFOLDER,
    Area,
    DocType,
)
from household_vault.reasons import PRIORITY, Reason
from household_vault.schemas import SCHEMAS, light_schema


def test_every_type_has_an_area_and_rules():
    for t in set(DocType) - {DocType.other}:
        assert t in AREA and t in OWNER and t in DATE_FIELD and t in REQUIRED and t in LABEL


def test_core_and_light_split_every_type():
    assert set(DocType) - {DocType.other} == CORE | LIGHT and not CORE & LIGHT


def test_service_records_are_split():
    assert "service_record" not in DocType.__members__
    assert AREA[DocType.appliance_service_record] is Area.purchases
    assert AREA[DocType.vehicle_service_record] is Area.vehicle


def test_vehicle_policy_files_under_insurance_linked_by_registration():
    assert AREA[DocType.vehicle_policy] is Area.insurance
    assert "registration_number" in REQUIRED[DocType.vehicle_policy]


def test_every_rule_names_real_schema_fields():
    for t in SCHEMAS:
        names = set(SCHEMAS[t].model_fields)
        rule = OWNER[t]
        assert set(rule.owner_fields) | set(rule.linked_fields) | REQUIRED[t] <= names
        assert DATE_FIELD[t] is None or DATE_FIELD[t] in names
        assert set(COPY_KEY[t]) <= names | {"last4"}


def test_schemas_cover_every_readable_type():
    assert set(SCHEMAS) == set(DocType) - {DocType.other, DocType.visit_recording}


def test_light_schema_fields():
    assert set(light_schema(DocType.utility_bill).model_fields) == {
        "person_name",
        "document_date",
        "expiry_date",
        "provider",
        "consumer_number",
    }


def test_reasons_are_all_in_the_priority_list():
    assert set(PRIORITY) == set(Reason) and PRIORITY[0] is Reason.locked


def test_areas_and_folders():
    assert set(AREA_FOLDER) == set(Area)
    assert AREA_FOLDER[Area.insurance] == "Insurance"
    assert set(SUBFOLDER) == {t for t in DocType if AREA.get(t) is Area.medical}


def test_purchases_belong_to_home_and_link_the_buyer():
    for t in (DocType.tax_invoice, DocType.warranty_card, DocType.amc):
        assert OWNER[t].home and OWNER[t].linked_fields == ("buyer",)
    assert not OWNER[DocType.vehicle_policy].home
    assert OWNER[DocType.registration_certificate].owner_fields == ("person_name",)
