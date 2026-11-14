import json
import typing
from pathlib import Path

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
from household_vault.schemas._coerce import Kind, field_kind


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


def _table_rows():
    return {
        t.value: {
            "area": AREA[t].value,
            "tier": "core" if t in CORE else "light",
            "home": OWNER[t].home,
            "owner_fields": list(OWNER[t].owner_fields),
            "linked_fields": list(OWNER[t].linked_fields),
            "date_field": DATE_FIELD[t],
            "required": sorted(REQUIRED[t]),
            "copy_key": list(COPY_KEY[t]),
            "subfolder": SUBFOLDER.get(t),
            "label": LABEL[t],
        }
        for t in sorted(set(DocType) - {DocType.other})
    }


def test_tables_match_the_committed_golden_file():
    golden = json.loads((Path(__file__).parent / "data" / "doctype_tables.json").read_text())
    assert golden["types"] == _table_rows()
    assert golden["area_folder"] == {a.value: f for a, f in AREA_FOLDER.items()}


def test_date_fields_are_dates_and_people_fields_are_names():
    for t, schema in SCHEMAS.items():
        if DATE_FIELD[t] is not None:
            assert field_kind(schema, DATE_FIELD[t]) == "date"
        rule = OWNER[t]
        for name in (*rule.owner_fields, *rule.linked_fields):
            assert _is_name_kind(schema, name), (t, name)


def _is_name_kind(schema, name):
    if field_kind(schema, name) == "name":
        return True
    args = typing.get_args(schema.model_fields[name].annotation)
    items = [a for a in args if typing.get_origin(a) is list]
    return bool(items) and any(
        isinstance(m, Kind) and m.kind == "name"
        for m in typing.get_args(typing.get_args(items[0])[0])[1:]
    )
