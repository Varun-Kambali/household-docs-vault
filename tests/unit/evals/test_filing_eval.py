import pytest

from evals.filing_eval import run_filing
from tests.fakes import EVAL_V1


def test_filing_eval_catches_copies_and_merges_nothing(oracle_dir, tmp_path, eval_slice):
    r = run_filing(EVAL_V1, "val", oracle_dir, tmp_path, only=eval_slice)
    assert (r["placement_matches_decision"], r["exact_copies_caught"]) == (1.0, 1.0)
    assert (r["wrong_merges"], r["secrets_found"]) == (0, 0)


def test_every_variant_runs_in_its_own_vault_and_nothing_is_left_over(
    oracle_dir, tmp_path, eval_slice
):
    r = run_filing(EVAL_V1, "val", oracle_dir, tmp_path, only=eval_slice)
    assert set(r["by_variant"]) == {"clean", "photo", "scan", "locked"}
    assert sorted(p.name for p in tmp_path.iterdir() if p.name != "oracle") == [
        "clean",
        "locked",
        "photo",
        "scan",
    ]
    assert (r["cvv_stored"], r["inbox_left"], r["undo_same_path"]) == (0, 0, 1.0)
    assert r["needs_a_look_share"]["expected_clean"] == 0.0
    assert r["by_variant"]["clean"]["undo_tried"] == 1  # one fileable clean document in the slice


def test_a_card_with_a_back_is_filed_through_the_upload_and_its_secrets_stay_out(
    oracle_dir, tmp_path
):
    r = run_filing(EVAL_V1, "val", oracle_dir, tmp_path, only=["card_front-6-photo"])
    photo = r["by_variant"]["photo"]
    assert (photo["should_file"], photo["filed_as_decided"], photo["secrets_found"]) == (1, 1, 0)


def test_the_masked_copy_stand_in_never_hides_a_missing_recording(tmp_path):
    from evals.filing_eval import MaskedCopyPages
    from household_vault.intake.sniff import FileKind
    from household_vault.reading.ollama import ModelUnavailable
    from household_vault.reading.recorded import recorded_engines
    from household_vault.reading.source import DocumentSource

    source = DocumentSource(FileKind.jpeg, data=b"x")
    known = "a" * 64
    pages = MaskedCopyPages(recorded_engines(tmp_path).pages, {known})
    assert [p.lines for p in pages.read_pages(source, "b" * 64, None)] == [[]]
    with pytest.raises(ModelUnavailable):
        pages.read_pages(source, known, None)
