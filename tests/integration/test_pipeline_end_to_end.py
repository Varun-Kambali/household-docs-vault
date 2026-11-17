import csv
import io

from vault_synth.cli import FORM_SPECS, HAND_DRAWN

from household_vault.filing.records import read_record
from household_vault.reading.engines import VisionPageReader
from household_vault.vaultroot import INBOX
from tests.conftest import _eval_docs, drop
from tests.fakes import EVAL_V1, OpenGateCards


def _picked():
    """One clean test-split document of each hand-drawn type and of four form types."""
    types = sorted(HAND_DRAWN, key=str) + sorted(FORM_SPECS, key=str)[:4]
    picked = []
    for t in types:
        doc = next(
            (
                d
                for d in _eval_docs()
                if d.doc_type == t and d.variant == "clean" and d.split == "test"
            ),
            None,
        )
        if doc is not None:
            picked.append(doc)
    return picked


def test_the_whole_pipeline_from_text_layers_and_photos(make_world):
    w = make_world(pages=VisionPageReader(None), cards=OpenGateCards())
    docs = _picked()
    assert len(docs) == 13
    for d in docs:
        drop(w.vault, d.files[0], (EVAL_V1 / d.files[0]).read_bytes())
    w.drain()
    assert w.vault.list_dir(INBOX) == []
    for d in docs:
        item = next(i for i in w.store.items(["filed", "asked"]) if i.original_name == d.files[0])
        if not d.expected_ask:
            assert item.state == "filed", (d.doc_id, item.reasons)
            row = w.store.document(item.document_id)
            assert row is not None and row.rel_path.startswith(f"{d.folder}/")
            assert read_record(w.vault, row.id).sha256 == row.sha256
        else:
            assert item.state == "asked" and item.reasons[0].value == d.expected_ask[0]
            assert item.rel_path.startswith("Needs a look/")
    log = next(e for e in w.vault.list_dir("_system/log"))
    rows = list(csv.reader(io.StringIO(w.vault.read_bytes(f"_system/log/{log.name}").decode())))
    steps = {r[1] for r in rows[1:]}
    assert {"noticed", "checked", "read", "filed"} <= steps
    assert len(rows) - 1 >= 3 * len(docs)
