"""A card whose front and back are two PDFs is one scanned PDF in the evals."""

import hashlib
import json

import pytest
from vault_synth.sets import load_set

from evals.filing_eval import run_filing
from evals.reading_eval import run_reading
from evals.recordings import files_as_filed, join_pdfs, oracle_recording
from household_vault.doctypes import DocType
from household_vault.intake.sniff import FileKind
from household_vault.reading.engines import Engines, VisionPageReader
from household_vault.reading.recorded import write_recording
from household_vault.reading.render import page_count
from household_vault.reading.source import DocumentSource
from tests.fakes import EVAL_V1, FakeOcr

TWO_PDFS = ["card_front-6-clean", "card_front-6-scan"]


def _doc(doc_id):
    return next(d for d in load_set(EVAL_V1) if d.doc_id == doc_id)


def _files(doc_id):
    return [(EVAL_V1 / n).read_bytes() for n in _doc(doc_id).files]


class _TruthModelsByAnyKey:
    """Answers with the truth of the card, whatever the key."""

    name = "any-key"

    def __init__(self, doc_id):
        self.doc = _doc(doc_id)

    def classify(self, ocr_text, sha256):
        return json.dumps({"doc_type": DocType.card_front.value})

    def fill(self, doc_type, images, ocr_text, sha256):
        return json.dumps(self.doc.fields)


class _SpyPages:
    def __init__(self):
        self.inner = VisionPageReader(ocr=FakeOcr())
        self.sources: list[DocumentSource] = []

    def read_pages(self, source, sha256, password):
        self.sources.append(source)
        return self.inner.read_pages(source, sha256, password)


@pytest.mark.parametrize("doc_id", TWO_PDFS)
def test_two_pdfs_join_into_one_two_page_pdf_with_the_same_bytes_every_time(doc_id):
    files = _files(doc_id)
    assert len(files) == 2
    first = join_pdfs(files)
    assert first == join_pdfs(files)
    assert page_count(first) == 2


def test_other_documents_keep_their_files():
    photo = _files("card_front-6-photo")
    assert files_as_filed(photo) == photo
    single = _files("health_policy-1-clean")
    assert files_as_filed(single) == single
    assert files_as_filed(_files("card_front-6-clean")) == [join_pdfs(_files("card_front-6-clean"))]


@pytest.mark.parametrize("doc_id", TWO_PDFS)
def test_reading_a_two_pdf_card_reads_one_pdf_and_records_it_by_its_hash(tmp_path, doc_id):
    pages = _SpyPages()
    rows = run_reading(
        EVAL_V1,
        "val",
        Engines(pages, _TruthModelsByAnyKey(doc_id)),
        record_to=tmp_path,
        resume=False,
        limit=None,
        only={doc_id},
    )
    assert len(rows) == 1
    joined = join_pdfs(_files(doc_id))
    (source,) = pages.sources
    assert (source.kind, source.data, source.images) == (FileKind.pdf, joined, None)
    assert page_count(joined) == 2
    assert [p.name for p in tmp_path.glob("*.json")] == [
        f"{hashlib.sha256(joined).hexdigest()}.json"
    ]


def test_filing_a_two_pdf_card_goes_through_the_inbox_not_the_photo_upload(oracle_dir, tmp_path):
    ids = ["card_front-6-clean", "card_front-6-photo"]
    for doc_id in ids:
        doc = _doc(doc_id)
        write_recording(oracle_dir, oracle_recording(doc, files_as_filed(_files(doc_id))))
    r = run_filing(EVAL_V1, "val", oracle_dir, tmp_path, only=ids)
    clean = r["by_variant"]["clean"]
    assert (clean["should_file"], clean["filed_as_decided"], clean["secrets_found"]) == (1, 1, 0)
    photo = r["by_variant"]["photo"]
    assert (photo["should_file"], photo["filed_as_decided"], photo["secrets_found"]) == (1, 1, 0)


def test_joined_bytes_do_not_depend_on_the_clock():
    import time

    files = _files("card_front-6-clean")
    first = join_pdfs(files)
    time.sleep(1.1)  # pdfium stamps the current second, so a later join would differ unfixed
    assert join_pdfs(files) == first
    assert b"/CreationDate(D:20000101000000+00'00')" in first
