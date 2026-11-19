"""The leak scan over everything the app writes, and the redaction that keeps numbers out of
logs. Cards here are the networks' published test numbers; a number that is not one is built at
runtime."""

import io
import logging

from reportlab.pdfgen import canvas

from household_vault.checks import TEST_CARD_NUMBERS, luhn_valid
from household_vault.leakscan import (
    install_log_redaction,
    redact,
    scan_outputs,
    scan_text,
    unscanned_files,
)
from household_vault.vaultroot import SECRETS_FILE

VISA = "4111111111111111"


def _other_card() -> str:
    """A 16-digit number that passes Luhn and is not a published test number."""
    body = "453201511283036"
    return body + next(d for d in "0123456789" if luhn_valid(body + d))


def test_app_output_scan_counts_test_cards_and_redacts(vault, settings):
    assert scan_text("4111 1111 1111 1111", allow_test_cards=False)
    assert scan_text("4111 1111 1111 1111", allow_test_cards=True) == []
    assert redact("card 4111111111111111 ok") == "card XXXXXXXXXXXX1111 ok"
    (settings.log_dir / "vault.log").write_text("oops 4111111111111111")
    assert scan_outputs(vault, settings.db_path, settings.log_dir)


def test_descriptions_show_only_the_last_four():
    (hit,) = scan_text(f"x {VISA} y", allow_test_cards=False)
    assert hit == "card-shaped XXXXXXXXXXXX1111"


def test_redact_keeps_the_separators_and_covers_every_hit():
    assert redact("4111-1111-1111-1111") == "XXXX-XXXX-XXXX-1111"
    assert redact("a 5555555555554444 b 378282246310005") == (
        "a XXXXXXXXXXXX4444 b XXXXXXXXXXX0005"
    )
    assert redact("no numbers here, 2026-11-20") == "no numbers here, 2026-11-20"


def test_every_published_test_number_is_redacted():
    for number in TEST_CARD_NUMBERS:
        assert number[:-4] not in redact(f"n={number}")


def test_the_log_filter_redacts_messages_and_arguments(caplog):
    install_log_redaction()
    log = logging.getLogger("household_vault.test_redaction")
    with caplog.at_level(logging.INFO, logger=log.name):
        log.info("read %s and 4111111111111111", _other_card())
    assert VISA[:-4] not in caplog.text
    assert _other_card()[:-4] not in caplog.text
    assert "XXXXXXXXXXXX" in caplog.text


def test_the_scan_reads_vault_text_pdf_text_and_leaves_the_secrets_file(vault, settings):
    vault.mkdirs("Home/Notes")
    vault.write_atomic("Home/Notes/note.txt", f"card {VISA}".encode())
    vault.write_atomic(SECRETS_FILE, VISA.encode())  # stands for the encrypted file
    hits = scan_outputs(vault, settings.db_path, settings.log_dir)
    assert hits == ["Home/Notes/note.txt: card-shaped XXXXXXXXXXXX1111"]

    buf = io.BytesIO()
    pdf = canvas.Canvas(buf)
    pdf.drawString(50, 700, f"number {_other_card()}")
    pdf.save()
    vault.write_atomic("Home/Notes/page.pdf", buf.getvalue())
    vault.unlink("Home/Notes/note.txt")
    (hit,) = scan_outputs(vault, settings.db_path, settings.log_dir)
    assert hit.startswith("Home/Notes/page.pdf: card-shaped XXXXXXXXXXXX")
    assert _other_card()[:-4] not in hit


def test_images_are_listed_as_not_scanned(vault):
    vault.write_atomic("Inbox/a.jpg", b"\xff\xd8\xff")
    vault.write_atomic("Inbox/b.txt", b"hello")
    assert unscanned_files(vault) == ["Inbox/a.jpg"]


def test_the_scan_reads_the_database_bytes_and_every_text_column(vault, settings, store):
    store.conn.execute("create table notes (id integer primary key, body text)")
    store.conn.execute("insert into notes (body) values (?)", (f"see {_other_card()}",))
    hits = scan_outputs(vault, settings.db_path, settings.log_dir)
    assert any("notes" in h and _other_card()[:-4] not in h for h in hits)


def test_the_scan_finds_a_known_secret_with_spaces_removed(vault, settings):
    secret = "9876 5432 1098"
    (settings.log_dir / "a.log").write_text("the number was 98765432 1098 here")
    hits = scan_outputs(vault, settings.db_path, settings.log_dir, known_secrets=[secret])
    assert len(hits) == 1 and "9876" not in hits[0] and hits[0].startswith("a.log")
    assert "1098" in hits[0]


def test_a_known_password_is_reported_without_its_value(vault, settings):
    (settings.log_dir / "a.log").write_text("pw=correct-horse-battery")
    (hit,) = scan_outputs(
        vault, settings.db_path, settings.log_dir, known_secrets=["correct-horse-battery"]
    )
    assert "correct" not in hit


def test_a_clean_world_has_no_hits(vault, settings):
    vault.write_atomic("Home/ok.json", b'{"x": 1.12345678901234}')
    assert scan_outputs(vault, settings.db_path, settings.log_dir) == []


def _logger_with_plain_handler(name: str):
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(logging.Formatter("%(message)s"))
    log = logging.getLogger(name)
    log.handlers = [handler]
    log.propagate = False
    log.setLevel(logging.DEBUG)
    return log, buf


def test_redact_hides_a_misread_number_and_spaced_or_dotted_forms():
    assert redact("misread 4111111111111112") == "misread XXXXXXXXXXXX1112"
    assert redact("4111 1111 1111 1111") == "XXXX XXXX XXXX 1111"
    assert redact("4111.1111.1111.1111") == "XXXX.XXXX.XXXX.1111"
    assert redact("version 1.2.3 on 2026-11-20 took 0.12345678901234 s") == (
        "version 1.2.3 on 2026-11-20 took 0.12345678901234 s"
    )


def test_redact_hides_digits_after_a_cvv_cvc_cid_or_pin_label():
    assert redact("cvv 737 and CVV: 1234") == "cvv XXX and CVV: XXXX"
    assert redact("cvc=123, Cid 4567, PIN 9876") == "cvc=XXX, Cid XXXX, PIN XXXX"
    assert redact("pinned 12 items") == "pinned 12 items"


def test_redact_hides_the_secrets_it_is_given():
    assert redact(f"master {MASTER} here", secrets=[MASTER]) == "master [removed] here"


MASTER = "synthetic-master-password"


def test_the_handler_redacts_the_final_text_including_a_traceback():
    install_log_redaction(lambda: [MASTER])
    log, buf = _logger_with_plain_handler("household_vault.t_tb")
    try:
        raise ValueError("bad card 5555555555554444 and " + MASTER)
    except ValueError:
        log.exception("failed")
    log.info("extra", extra={"number": "4111111111111111"})
    out = buf.getvalue()
    assert "5555555555554444" not in out and MASTER not in out
    assert "XXXXXXXXXXXX4444" in out and "Traceback" in out


def test_a_bad_format_call_does_not_raise_and_is_still_redacted():
    install_log_redaction()
    log, buf = _logger_with_plain_handler("household_vault.t_bad")
    log.warning("two args %s %s 4111111111111111", 1)
    assert "4111111111111111" not in buf.getvalue()


def test_the_scan_finds_digits_after_a_cvv_label(vault, settings):
    vault.write_atomic("Home/note.txt", b"the cvv 737 was here")
    (hit,) = scan_outputs(vault, settings.db_path, settings.log_dir)
    assert hit == "Home/note.txt: digits after a cvv, cvc, cid or pin label"
    vault.write_atomic("Home/note.txt", b"the cvv XXX was here")
    assert scan_outputs(vault, settings.db_path, settings.log_dir) == []


def test_a_card_record_is_scanned_for_any_long_digit_run(vault, settings):
    vault.mkdirs("_system/records")
    sha = "0123456789012345678901234567890123456789012345678901234567890123"
    body = f'{{"doc_type": "card_front", "sha256": "{sha}", "text": "4111111111111112"}}'
    vault.write_atomic("_system/records/a.json", body.encode())
    vault.write_atomic("Home/other.txt", b"order 4111111111111112")
    hits = scan_outputs(vault, settings.db_path, settings.log_dir)
    assert hits == ["_system/records/a.json: card-shaped XXXXXXXXXXXX1112"]


def test_the_database_card_columns_are_scanned_for_any_long_digit_run(vault, settings, store):
    store.conn.execute(
        "insert into items (sha256, original_name, origin, state, created_at, updated_at, reading)"
        " values ('a', 'a.jpg', 'inbox', 'queued', 'x', 'x', ?)",
        ('{"lines": ["4111111111111112"]}',),
    )
    hits = scan_outputs(vault, settings.db_path, settings.log_dir)
    assert any(h.startswith("vault.db:items.reading") for h in hits)


def test_an_id_made_only_of_digits_is_not_a_card_number_in_a_card_record(vault, settings):
    vault.mkdirs("_system/records")
    body = '{"doc_type": "card_front", "secret_ref": "12345678-1234-1234-1234-123456789012"}'
    vault.write_atomic("_system/records/b.json", body.encode())
    assert scan_outputs(vault, settings.db_path, settings.log_dir) == []


def test_a_formatter_that_reads_the_args_still_works_and_its_line_is_redacted():
    install_log_redaction()

    class AccessFormatter(logging.Formatter):
        def format(self, record):
            client, request = record.args[0], record.args[1]
            return f"{client} - {request}"

    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(AccessFormatter())
    log = logging.getLogger("household_vault.t_access")
    log.handlers = [handler]
    log.propagate = False
    log.setLevel(logging.INFO)
    log.info('%s - "%s"', "4111111111111111", "GET /x")
    assert buf.getvalue().strip() == "XXXXXXXXXXXX1111 - GET /x"


def _luhn_check_digit(body: str) -> str:
    return next(d for d in "0123456789" if luhn_valid(body + d))


def test_values_that_sit_side_by_side_in_the_database_file_do_not_join_into_a_number(
    vault, settings, store
):
    """A hash tail and a date (or any two values) are stored back to back; a scan over the raw
    file would read their digits as one number that passes the card check by chance."""
    first = "x1234567890123"
    second = _luhn_check_digit("1234567890123") + "z"
    assert not luhn_valid("1234567890123")
    store.conn.execute("create table notes (id integer primary key, a text, b text)")
    store.conn.execute("insert into notes (a, b) values (?, ?)", (first, second))
    raw = "".join(
        p.read_bytes().decode("latin-1")
        for p in (settings.db_path, settings.db_path.with_name("vault.db-wal"))
        if p.is_file()
    )
    assert scan_text(raw, allow_test_cards=False)  # the raw bytes do join into a number
    assert scan_outputs(vault, settings.db_path, settings.log_dir) == []


def test_a_known_card_number_in_a_deleted_row_is_still_found_in_the_file(vault, settings, store):
    store.conn.execute("create table notes (id integer primary key, body text)")
    store.conn.execute("insert into notes (body) values (?)", (f"n {VISA}",))
    store.conn.execute("insert into notes (body) values (?)", ("n 4111 1111 1111 1111",))
    store.conn.execute("insert into notes (body) values (?)", ("n 4111-1111-1111-1111",))
    store.conn.execute("delete from notes")
    hits = scan_outputs(vault, settings.db_path, settings.log_dir, known_secrets=[VISA])
    files = {h.split(":")[0] for h in hits if "known secret" in h}
    assert files & {"vault.db", "vault.db-wal"}
    assert all(VISA[:-4] not in h for h in hits)


def test_a_known_password_in_the_wal_is_found_without_its_value(vault, settings, store):
    store.conn.execute("create table notes (id integer primary key, body text)")
    store.conn.execute("insert into notes (body) values (?)", ("pw=correct-horse-battery",))
    hits = scan_outputs(
        vault, settings.db_path, settings.log_dir, known_secrets=["correct-horse-battery"]
    )
    assert hits and all("correct" not in h for h in hits)


def test_a_misread_number_in_a_card_text_column_is_still_flagged(vault, settings, store):
    misread = "4111111111111112"
    assert not luhn_valid(misread)
    store.conn.execute(
        "insert into items (sha256, original_name, origin, state, created_at, updated_at, reading)"
        " values ('a', 'a.jpg', 'inbox', 'queued', 'x', 'x', ?)",
        (f'{{"lines": ["{misread}"]}}',),
    )
    hits = scan_outputs(vault, settings.db_path, settings.log_dir)
    assert any(h.startswith("vault.db:items.reading") and h.endswith("1112") for h in hits)


def test_a_document_id_is_not_an_aadhaar_number(vault, settings):
    """A 32-digit hex id can hold a 12-digit run that passes the Aadhaar check by chance."""
    from tests.conftest import valid_aadhaar

    number = valid_aadhaar()
    ident = f"ab{number}" + "cdef0123456789abcdef"[: 30 - len(number)]
    assert len(ident) == 32
    (settings.log_dir / "vault.log").write_text(f'{{"id": "{ident}"}}')
    assert scan_outputs(vault, settings.db_path, settings.log_dir) == []
    (settings.log_dir / "vault.log").write_text(f"number {number} here")
    assert scan_outputs(vault, settings.db_path, settings.log_dir)
