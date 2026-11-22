"""The two extra sets that grow the search eval's vault: eval-v1's counts, clean documents only,
and nothing that makes the app ask."""

from collections import Counter
from pathlib import Path

import pytest
from vault_synth.cli import generate
from vault_synth.model import SynthDoc
from vault_synth.sets import SETS, base_prefix

from household_vault.doctypes import DocType


@pytest.fixture(scope="module")
def x1(tmp_path_factory: pytest.TempPathFactory) -> list[SynthDoc]:
    out = tmp_path_factory.mktemp("x1")
    return generate("search-x1", out, splits=("val", "test"), variants=("clean",))


def test_the_extra_sets_ask_nothing() -> None:
    for name, seed in (("search-x1", 11), ("search-x2", 12)):
        spec = SETS[name]
        assert spec.seed == seed
        assert (spec.outsider_rate, spec.ambiguous_rate, spec.missing_required_rate) == (0, 0, 0)
        assert (spec.per_type_hand, spec.per_type_form) == (
            SETS["eval-v1"].per_type_hand,
            SETS["eval-v1"].per_type_form,
        )


def test_every_extra_document_is_clean_and_would_file(x1: list[SynthDoc]) -> None:
    assert {d.variant for d in x1} == {"clean"}
    assert [d for d in x1 if d.expected_ask] == []
    assert all(d.owner is not None for d in x1)


def test_extra_counts_follow_eval_v1(x1: list[SynthDoc]) -> None:
    for split in ("val", "test"):
        per_type = Counter(d.doc_type for d in x1 if d.split == split)
        assert len(per_type) == 50
        assert sum(per_type.values()) == 9 * 2 + 41
        assert per_type[DocType.tax_invoice] == 2 and per_type[DocType.passport] == 1


def test_extra_ids_name_their_set(x1: list[SynthDoc]) -> None:
    assert base_prefix(SETS["eval-v1"]) == ""
    assert all(d.doc_id.startswith("search-x1-") and d.set_name == "search-x1" for d in x1)
    assert len({d.doc_id for d in x1}) == len(x1)


def test_extra_files_are_written_and_no_other_variant(tmp_path: Path) -> None:
    docs = generate(
        "search-x2", tmp_path, splits=("val",), variants=("clean",), types=[DocType.card_front]
    )
    names = {p.name for p in tmp_path.iterdir()}
    assert not any("-photo" in n or "-scan" in n or "-locked" in n for n in names)
    assert all((tmp_path / f).exists() for d in docs for f in d.files)
