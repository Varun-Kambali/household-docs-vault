"""apply_query, truth_value and status_of on small hand-built documents with known answers, so a
wrong truth cannot pass by being regenerated from itself."""

from datetime import date

from vault_synth.model import SynthDoc

from evals.search_set import EVAL_TODAY, apply_query, status_of, truth_value
from household_vault.doctypes import Area, DocType
from household_vault.search.dates import DateRange
from household_vault.search.query import Query


def make(
    doc_id: str,
    doc_type: DocType,
    fields: dict[str, object],
    *,
    owner: str | None = "p1",
    linked: list[str] | None = None,
    ask: list[str] | None = None,
) -> SynthDoc:
    from household_vault.doctypes import AREA

    return SynthDoc(
        doc_id=doc_id,
        base_id=doc_id,
        doc_type=doc_type,
        person="x",
        variant="clean",
        files=[],
        fields=fields,  # type: ignore[arg-type]
        printed={},
        lines=[],
        field_lines={},
        owner=owner,
        linked_people=linked if linked is not None else ([owner] if owner else []),
        area=AREA[doc_type].value,
        expected_ask=ask or [],
    )


HEALTH = make(
    "health",
    DocType.health_policy,
    {"insurer": "Niva Bupa Health Insurance Company Limited", "end_date": "2027-02-10"},
    owner="p2",
    linked=["p2", "p1"],
)
VEHICLE = make(
    "vehicle",
    DocType.vehicle_policy,
    {"insurer": "Bajaj Allianz General Insurance", "end_date": "2026-09-01"},
    owner="p3",
)
INVOICE = make(
    "invoice",
    DocType.tax_invoice,
    {"seller": "Croma", "invoice_date": "2026-03-04", "amount": "31990"},
    owner="home",
    linked=["p3"],
)
AADHAAR = make("aadhaar", DocType.aadhaar, {"holder": "KAVITA RAO", "number": "3122 0950 8709"})
UNFILED = make(
    "unfiled",
    DocType.health_policy,
    {"insurer": "Niva Bupa", "end_date": "2027-02-10"},
    owner=None,
    ask=["person_unknown"],
)
DOCS = [HEALTH, VEHICLE, INVOICE, AADHAAR, UNFILED]


def test_a_person_matches_the_owner_or_a_linked_person() -> None:
    assert apply_query(Query(intent="list", people=["p1"]), DOCS) == ["health", "aadhaar"]
    assert apply_query(Query(intent="list", people=["p2"]), DOCS) == ["health"]
    assert apply_query(Query(intent="list", people=["home"]), DOCS) == ["invoice"]
    assert apply_query(Query(intent="list", people=["p3"]), DOCS) == ["vehicle", "invoice"]


def test_areas_expand_to_types_and_a_filed_document_only() -> None:
    q = Query(intent="list", areas=[Area.insurance])
    assert apply_query(q, DOCS) == ["health", "vehicle"]  # the unfiled one never matches
    q = Query(intent="list", areas=[Area.purchases], types=[DocType.aadhaar])
    assert apply_query(q, DOCS) == ["invoice", "aadhaar"]


def test_the_role_field_range_with_a_forward_start_at_today() -> None:
    forward = Query(
        intent="list",
        role="expiry",
        range=DateRange(start=EVAL_TODAY, end=date(2027, 3, 1)),
    )
    # the vehicle policy ended before today; the invoice and the Aadhaar have no expiry role
    assert apply_query(forward, DOCS) == ["health"]
    past = Query(
        intent="list",
        role="purchase",
        range=DateRange(start=date(2026, 1, 1), end=date(2026, 12, 31)),
    )
    assert apply_query(past, DOCS) == ["invoice"]


def test_a_document_with_no_role_date_is_left_out() -> None:
    q = Query(intent="list", role="document", range=DateRange(end=date(2030, 1, 1)))
    assert apply_query(q, [AADHAAR, INVOICE]) == ["invoice"]  # Aadhaar has no document date
    q = Query(intent="list", role="expiry", range=DateRange(end=date(2030, 1, 1)))
    assert apply_query(q, [INVOICE]) == []


def test_a_place_is_a_contained_phrase_of_the_place_field() -> None:
    assert apply_query(Query(intent="list", place="Niva Bupa"), DOCS) == ["health"]
    assert apply_query(Query(intent="list", place="niva"), DOCS) == ["health"]
    assert apply_query(Query(intent="list", place="Bupa Niva"), DOCS) == []
    assert apply_query(Query(intent="list", place="Cro"), DOCS) == []
    assert apply_query(Query(intent="list", place="Croma"), DOCS) == ["invoice"]


def test_truth_value_for_a_date_an_amount_an_identifier_and_a_list() -> None:
    assert truth_value(HEALTH, "end_date") == "2027-02-10"
    assert truth_value(INVOICE, "amount") == "31990"
    assert truth_value(AADHAAR, "number") == "3122 0950 8709"
    parts = [{"part": "Compressor", "years": "10"}, {"part": "Product", "years": "1"}]
    card = make(
        "w", DocType.warranty_card, {"purchase_date": "2026-05-26", "warranty_parts": parts}
    )
    assert truth_value(card, "warranty_parts") == parts
    assert truth_value(HEALTH, "nominee") is None and truth_value(HEALTH, None) is None


def test_status_names_each_warranty_part_and_the_validity() -> None:
    parts = [{"part": "Compressor", "years": "10"}, {"part": "Product", "years": "1"}]
    card = make(
        "w", DocType.warranty_card, {"purchase_date": "2026-05-26", "warranty_parts": parts}
    )
    assert status_of(card, "warranty_parts") == {"Compressor": True, "Product": True}
    old = make("o", DocType.warranty_card, {"purchase_date": "2024-05-26", "warranty_parts": parts})
    assert status_of(old, "warranty_parts") == {"Compressor": True, "Product": False}
    assert status_of(HEALTH, "end_date") == {"valid": True}
    assert status_of(VEHICLE, "end_date") == {"valid": False}
    assert status_of(HEALTH, "insurer") is None
    # the day itself still holds; the day after does not
    assert status_of(make("e", DocType.health_policy, {"end_date": "2026-11-20"}), "end_date") == {
        "valid": True
    }
    assert status_of(make("e", DocType.health_policy, {"end_date": "2026-11-19"}), "end_date") == {
        "valid": False
    }
