import hashlib
import io
from datetime import datetime

import pytest
from PIL import Image
from reportlab.lib.pdfencrypt import StandardEncryption

from household_vault.db import Store
from household_vault.intake import checks
from household_vault.intake.checks import check_file
from household_vault.intake.sniff import FileKind
from household_vault.vaultroot import VaultRoot
from tests.conftest import item_id, row

JPEG_HEAD = b"\xff\xd8\xff\xe0\x00\x10JFIF"


def _locked() -> bytes:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=(300, 400), encrypt=StandardEncryption("pw"))
    pdf.drawString(40, 350, "Synthetic page")
    pdf.save()
    return buf.getvalue()


LOCKED_PDF = _locked()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize(
    ("content", "outcome"),
    [
        (b"", "empty"),
        (b"PK\x03\x04", "unsupported"),
        (JPEG_HEAD + b"\x00" * 10, "damaged"),
        (b"%PDF-1.4 broken", "damaged"),
        (LOCKED_PDF, "locked"),
    ],
)
def test_bad_files_are_named(vault: VaultRoot, store: Store, content: bytes, outcome: str) -> None:
    vault.write_atomic("Inbox/x.pdf", content)
    assert check_file(vault, "Inbox/x.pdf", store, {}, item_id=None).outcome == outcome


def test_good_files_report_kind_size_pages(
    vault: VaultRoot, store: Store, clean_pdf_bytes: bytes
) -> None:
    vault.write_atomic("Inbox/x.bin", clean_pdf_bytes)
    r = check_file(vault, "Inbox/x.bin", store, {}, item_id=None)
    assert (r.outcome, r.kind, r.pages, r.size, r.sha256) == (
        "ok",
        FileKind.pdf,
        1,
        len(clean_pdf_bytes),
        sha(clean_pdf_bytes),
    )


@pytest.mark.parametrize(("fmt", "kind"), [("PNG", FileKind.png), ("JPEG", FileKind.jpeg)])
def test_images_pass_pillow_verify(
    vault: VaultRoot, store: Store, fmt: str, kind: FileKind
) -> None:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, format=fmt)
    vault.write_atomic("Inbox/p.dat", buf.getvalue())
    r = check_file(vault, "Inbox/p.dat", store, {}, item_id=None)
    assert (r.outcome, r.kind, r.pages) == ("ok", kind, None)


def test_heic_and_audio_are_taken_by_signature(vault: VaultRoot, store: Store) -> None:
    vault.write_atomic("Inbox/a.m4a", b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 20)
    vault.write_atomic("Inbox/b.heic", b"\x00\x00\x00\x18ftypheic" + b"\x00" * 20)
    assert check_file(vault, "Inbox/a.m4a", store, {}, item_id=None).kind is FileKind.audio
    assert check_file(vault, "Inbox/b.heic", store, {}, item_id=None).outcome == "ok"


def test_duplicates_of_filed_documents_and_within_one_pass(
    vault: VaultRoot, store: Store, clean_pdf_bytes: bytes
) -> None:  # Review Focus 6
    store.add_document(
        row(
            "d1",
            item_id=item_id(store),
            sha256=sha(clean_pdf_bytes),
            rel_path="Home/Purchases/a.pdf",
        ),
        [],
        [],
    )
    vault.write_atomic("Inbox/a (1).pdf", clean_pdf_bytes)
    r = check_file(vault, "Inbox/a (1).pdf", store, {}, item_id=None)
    assert r.duplicate_of == "Home/Purchases/a.pdf"
    other = clean_pdf_bytes + b"\n%"
    vault.write_atomic("Inbox/b.pdf", other)
    vault.write_atomic("Inbox/b (1).pdf", other)
    seen: dict[str, str] = {}
    first, second = (
        check_file(vault, f"Inbox/{n}", store, seen, item_id=None) for n in ("b.pdf", "b (1).pdf")
    )
    assert (first.outcome, second.outcome, second.duplicate_of) == (
        "ok",
        "duplicate",
        "Inbox/b.pdf",
    )


def test_an_item_is_never_its_own_duplicate(
    vault: VaultRoot, store: Store, clean_pdf_bytes: bytes, now: datetime
) -> None:  # ruling 12
    vault.write_atomic("Needs a look/a.pdf", clean_pdf_bytes)
    asked = store.add_item(sha(clean_pdf_bytes), "a.pdf", "Needs a look/a.pdf", now)
    store.update_item(asked.id, state="asked")
    assert check_file(vault, "Needs a look/a.pdf", store, {}, item_id=asked.id).outcome == "ok"
    vault.write_atomic("Inbox/a (1).pdf", clean_pdf_bytes)
    dup = check_file(vault, "Inbox/a (1).pdf", store, {}, item_id=None)
    assert (dup.outcome, dup.duplicate_of) == ("duplicate", "Needs a look/a.pdf")
    kept = check_file(vault, "Inbox/a (1).pdf", store, {}, item_id=None, skip_duplicate=True)
    assert kept.outcome == "ok"


def test_a_file_that_vanishes_raises_gone(vault: VaultRoot, store: Store) -> None:
    from household_vault.vaultroot import VaultGone

    with pytest.raises(VaultGone):
        check_file(vault, "Inbox/none.pdf", store, {}, item_id=None)


def test_damaged_files_are_not_remembered_for_the_pass(vault: VaultRoot, store: Store) -> None:
    vault.write_atomic("Inbox/x.pdf", b"%PDF-1.4 broken")
    seen: dict[str, str] = {}
    check_file(vault, "Inbox/x.pdf", store, seen, item_id=None)
    assert seen == {}
    assert checks.__name__
