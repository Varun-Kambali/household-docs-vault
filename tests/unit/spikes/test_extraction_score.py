from pathlib import Path

from household_vault.schemas import (
    HealthPolicy,
    LabReport,
    Prescription,
    VehiclePolicy,
    WarrantyCard,
)
from spikes.extraction.candidates import Candidate
from spikes.extraction.run import run_candidate
from spikes.extraction.score import score_doc


class FakeCandidate(Candidate):
    def __init__(self, load_error: BaseException | None = None, kind="vision"):
        super().__init__(name="fake", runtime="ollama", kind=kind)
        self.load_error = load_error
        self.unloaded = False

    def load(self) -> None:
        if self.load_error:
            raise self.load_error

    def extract(self, doc_files: list[Path], ocr_text: str | None, schema_json: str) -> str:
        return "{}"

    def unload(self) -> None:
        self.unloaded = True


def test_invalid_json_counts_as_failure():
    s = score_doc({"policy_number": "P1"}, "{not json", HealthPolicy)
    assert s.valid_json is False and s.exact == {"policy_number": False}


def test_non_object_json_is_invalid():
    s = score_doc({"policy_number": "P1"}, "[1, 2]", HealthPolicy)
    assert s.valid_json is False and s.exact == {"policy_number": False}


def test_extra_keys_are_ignored_not_fatal():
    s = score_doc({"policy_number": "P1"}, '{"policy_number": "P1", "x": 1}', HealthPolicy)
    assert s.valid_json is True
    assert s.exact["policy_number"] is True


def test_missing_and_null_fields_are_wrong():
    s = score_doc(
        {"insurer": "A", "nominee": "B"}, '{"insurer": "A", "nominee": null}', HealthPolicy
    )
    assert s.exact == {"insurer": True, "nominee": False}


def test_dates_compare_by_value():
    for got in ("18/01/2027", "18-01-2027", "18 Jan 2027", "2027-01-18"):
        s = score_doc({"end_date": "2027-01-18"}, f'{{"end_date": "{got}"}}', HealthPolicy)
        assert s.exact["end_date"] is True, got
    s = score_doc({"end_date": "2027-01-18"}, '{"end_date": "2027-01-19"}', HealthPolicy)
    assert s.exact["end_date"] is False
    s = score_doc({"end_date": "2027-01-18"}, '{"end_date": "soon"}', HealthPolicy)
    assert s.exact["end_date"] is False


def test_amounts_ignore_symbols_commas_and_spaces():
    for got in ('"₹ 5,00,000"', '"Rs. 500000"', "500000", '"5,00,000.00"'):
        s = score_doc({"sum_insured": "500000"}, f'{{"sum_insured": {got}}}', HealthPolicy)
        assert s.exact["sum_insured"] is True, got
    s = score_doc({"sum_insured": "500000"}, '{"sum_insured": "50000"}', HealthPolicy)
    assert s.exact["sum_insured"] is False


def test_percent_sign_is_ignored():
    s = score_doc({"ncb_percent": "20"}, '{"ncb_percent": "20%"}', VehiclePolicy)
    assert s.exact["ncb_percent"] is True


def test_strings_ignore_case_and_whitespace():
    s = score_doc({"insurer": "Star  Health"}, '{"insurer": " star health "}', HealthPolicy)
    assert s.exact["insurer"] is True


def test_semicolon_list_compares_as_a_set():
    s = score_doc(
        {"insured": "Asha Rao; Ravi Rao"}, '{"insured": ["Ravi Rao", "Asha Rao"]}', HealthPolicy
    )
    assert s.exact["insured"] is True
    s = score_doc({"insured": "Asha Rao; Ravi Rao"}, '{"insured": ["Asha Rao"]}', HealthPolicy)
    assert s.exact["insured"] is False


def test_medicines_compare_by_item():
    truth = {"medicines": "Cetirizine 10 mg 1-1-1 5 days;Metformin 850 mg 0-0-1 7 days"}
    got = (
        '{"medicines": [{"name": "Metformin", "dose": "850 mg", "timing": "0-0-1",'
        ' "duration": "7 days"}, {"name": "Cetirizine", "dose": "10 mg", "timing": "1-1-1",'
        ' "duration": "5 days"}]}'
    )
    assert score_doc(truth, got, Prescription).exact["medicines"] is True
    wrong = got.replace("850 mg", "500 mg")
    assert score_doc(truth, wrong, Prescription).exact["medicines"] is False


def test_tests_and_warranty_parts_items():
    s = score_doc(
        {"tests": "Haemoglobin=12.2 g/dL;HbA1c=4.2 %"},
        '{"tests": [{"name": "HbA1c", "value": "4.2", "unit": "%"},'
        ' {"name": "Haemoglobin", "value": "12.2", "unit": "g/dL"}]}',
        LabReport,
    )
    assert s.exact["tests"] is True
    s = score_doc(
        {"warranty_parts": "Magnetron:2;Product:1"},
        '{"warranty_parts": [{"part": "Product", "years": 1}, {"part": "Magnetron", "years": 2}]}',
        WarrantyCard,
    )
    assert s.exact["warranty_parts"] is True


def test_load_failure_recorded_not_raised():
    for err in (MemoryError(), RuntimeError("model requires more system memory")):
        c = FakeCandidate(load_error=err)
        r = run_candidate(c, docs=[])
        assert r.status == "did_not_fit" and r.scores == []
        assert c.unloaded is True


def test_empty_run_is_ok():
    assert run_candidate(FakeCandidate(), docs=[]).status == "ok"
