import pytest

from household_vault.leakscan import scan_outputs
from household_vault.secrets.store import SecretsLocked, SecretsStore
from household_vault.vaultroot import SECRETS_FILE
from tests.conftest import MASTER_PASSWORD

CARD = "4111111111111111"
CVV = "737"


def test_store_is_kdbx4_and_needs_the_master_password(vault):
    SecretsStore.create(vault, MASTER_PASSWORD)
    with pytest.raises(SecretsLocked):
        SecretsStore.open(vault, "wrong")
    assert SecretsStore.open(vault, MASTER_PASSWORD).version[0] == 4


def test_create_refuses_an_existing_file(vault):
    SecretsStore.create(vault, MASTER_PASSWORD)
    before = vault.read_bytes(SECRETS_FILE)
    with pytest.raises(FileExistsError):
        SecretsStore.create(vault, "another-password")
    assert vault.read_bytes(SECRETS_FILE) == before


def test_opening_a_missing_or_damaged_file_says_locked(vault):
    with pytest.raises(SecretsLocked):
        SecretsStore.open(vault, MASTER_PASSWORD)
    vault.write_atomic(SECRETS_FILE, b"not a keepass file")
    with pytest.raises(SecretsLocked):
        SecretsStore.open(vault, MASTER_PASSWORD)


def test_a_card_is_saved_with_protected_fields_and_attachments(vault):
    store = SecretsStore.create(vault, MASTER_PASSWORD)
    uid = store.add_card(
        "Test Bank card ending 1111",
        CARD,
        "09/29",
        CVV,
        "Test Holder",
        [("front.jpg", b"front bytes"), ("back.jpg", b"back bytes")],
    )
    again = SecretsStore.open(vault, MASTER_PASSWORD)
    assert again.entries("Cards") == [uid] and again.entries("Documents") == []
    fields = again.entry_fields(uid)
    assert (fields["number"], fields["cvv"], fields["expiry"], fields["holder"]) == (
        CARD,
        CVV,
        "09/29",
        "Test Holder",
    )
    assert fields["title"] == "Test Bank card ending 1111"
    assert again.attachment_names(uid) == ["front.jpg", "back.jpg"]
    assert again.attachment(uid, "back.jpg") == b"back bytes"


def test_the_file_holds_no_plain_secret(vault, settings):
    store = SecretsStore.create(vault, MASTER_PASSWORD)
    store.add_card("T card ending 1111", CARD, None, CVV, None, [("front.jpg", b"unique-photo")])
    data = vault.read_bytes(SECRETS_FILE)
    for plain in (CARD.encode(), b"unique-photo", MASTER_PASSWORD.encode()):
        assert plain not in data
    assert scan_outputs(vault, settings.db_path, settings.log_dir, known_secrets=[CARD]) == []


def test_a_missing_expiry_cvv_and_holder_are_left_out(vault):
    store = SecretsStore.create(vault, MASTER_PASSWORD)
    uid = store.add_card("T card ending 1111", CARD, None, None, None, [])
    assert set(store.entry_fields(uid)) == {"title", "number"}


def test_a_pdf_password_goes_in_documents_and_is_not_added_twice(vault):
    store = SecretsStore.create(vault, MASTER_PASSWORD)
    first = store.add_pdf_password("Policy.pdf", "pdf-pass-one")
    assert store.add_pdf_password("Policy.pdf", "pdf-pass-one") == first
    other = store.add_pdf_password("Policy.pdf", "pdf-pass-two")
    assert other != first
    assert store.entries("Documents") == [first, other] and store.entries("Cards") == []
    assert SecretsStore.open(vault, MASTER_PASSWORD).entry_fields(first)["password"] == (
        "pdf-pass-one"
    )


def test_has_entry_and_unknown_entries(vault):
    store = SecretsStore.create(vault, MASTER_PASSWORD)
    uid = store.add_card("T card ending 1111", CARD, None, None, None, [])
    assert store.has_entry(uid) and not store.has_entry("00000000-0000-0000-0000-000000000000")
    assert not store.has_entry("not a uuid")
    with pytest.raises(KeyError):
        store.entry_fields("00000000-0000-0000-0000-000000000000")


def test_a_failed_save_leaves_neither_the_file_nor_the_store_changed(vault, monkeypatch):
    store = SecretsStore.create(vault, MASTER_PASSWORD)
    before = vault.read_bytes(SECRETS_FILE)

    def broken(rel: str, data: bytes) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(vault, "write_atomic", broken)
    with pytest.raises(OSError, match="disk full"):
        store.add_card("T card ending 1111", CARD, None, None, None, [])
    monkeypatch.undo()
    assert vault.read_bytes(SECRETS_FILE) == before
    assert store.entries("Cards") == []
    store.add_card("T card ending 1111", CARD, None, None, None, [])
    assert len(store.entries("Cards")) == 1


def test_an_edit_made_elsewhere_is_kept(vault):
    """Another KeePass app saved the file after this store opened it: the next save builds on
    that file, never on the older copy in memory."""
    mine = SecretsStore.create(vault, MASTER_PASSWORD)
    other = SecretsStore.open(vault, MASTER_PASSWORD)
    first = other.add_pdf_password("Elsewhere.pdf", "pw-elsewhere")
    second = mine.add_pdf_password("Here.pdf", "pw-here")
    assert SecretsStore.open(vault, MASTER_PASSWORD).entries("Documents") == [first, second]


def test_the_repr_and_errors_never_show_a_secret(vault):
    store = SecretsStore.create(vault, MASTER_PASSWORD)
    assert MASTER_PASSWORD not in repr(store) and MASTER_PASSWORD not in str(store)
    with pytest.raises(SecretsLocked) as exc:
        SecretsStore.open(vault, "wrong-password-text")
    assert "wrong-password-text" not in str(exc.value)


def test_two_instances_that_write_at_once_keep_both_entries(vault):
    import threading

    SecretsStore.create(vault, MASTER_PASSWORD)
    first = SecretsStore.open(vault, MASTER_PASSWORD)
    second = SecretsStore.open(vault, MASTER_PASSWORD)
    go = threading.Event()
    real_save = first._save

    def slow_save() -> None:
        go.wait(5)
        real_save()

    first._save = slow_save  # type: ignore[method-assign]
    box: dict[str, str] = {}
    t = threading.Thread(
        target=lambda: box.setdefault(
            "card", first.add_card("T card ending 1111", CARD, None, None, None, [])
        )
    )
    t.start()
    threading.Timer(0.2, go.set).start()
    second.add_pdf_password("Policy.pdf", "pdf-pass-one")
    t.join()
    fresh = SecretsStore.open(vault, MASTER_PASSWORD)
    assert len(fresh.entries("Cards")) == 1 and len(fresh.entries("Documents")) == 1


def test_a_save_after_the_file_vanished_is_refused(vault):
    store = SecretsStore.create(vault, MASTER_PASSWORD)
    vault.unlink(SECRETS_FILE)
    with pytest.raises(SecretsLocked):
        store.add_pdf_password("x", "pw-x")
    assert not vault.exists(SECRETS_FILE)


def test_a_card_added_with_its_own_id_is_found_again_by_that_id(vault):
    import uuid

    store = SecretsStore.create(vault, MASTER_PASSWORD)
    uid = str(uuid.uuid4())
    assert store.add_card("T card ending 1111", CARD, None, None, None, [], uid=uid) == uid
    assert store.add_card("T card ending 1111", CARD, None, None, None, [], uid=uid) == uid
    assert store.entries("Cards") == [uid]
