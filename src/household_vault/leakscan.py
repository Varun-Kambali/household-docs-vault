"""The one scanner for card-shaped and Aadhaar-shaped numbers, and what is built on it.

`scan_text` finds them and describes each with its last four digits only (CI logs are public).
`redact` takes every digit but the last four out of a text, and `install_log_redaction` applies
it to every log record. `scan_outputs` walks everything the app writes (the vault except the
encrypted secrets file, the database, the logs) for such numbers and for known secrets, so a
test can show that no secret travelled anywhere but `Secrets.kdbx`.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import weakref
from collections.abc import Callable, Collection
from pathlib import Path

from household_vault.checks import find_numbers
from household_vault.reading.render import DamagedFileError, LockedPdfError, page_count, text_layer
from household_vault.vaultroot import RECORDS, SECRETS_FILE, VaultGone, VaultPathError, VaultRoot

IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".heic", ".heif", ".gif", ".webp", ".tif"})
_LABEL = {"card": "card-shaped", "aadhaar": "Aadhaar-shaped"}
_SEPARATORS = re.compile(r"[\s-]+")


def _masked(digits: str) -> str:
    """All digits but the last four as X."""
    return "X" * max(len(digits) - 4, 0) + digits[-4:]


def scan_text(text: str, *, allow_test_cards: bool, any_long_run: bool = False) -> list[str]:
    """Masked descriptions of every card-shaped or Aadhaar-shaped number in text, once each.

    With `allow_test_cards` False the networks' published test numbers count too: in the
    synthetic vault they are the secrets. With `any_long_run` every 13 to 19 digit run counts, as
    it does in the text of a card.
    """
    found: list[str] = []
    for hit in find_numbers(text, allow_test_cards=allow_test_cards, any_long_run=any_long_run):
        line = f"{_LABEL[hit.kind]} {_masked(hit.digits)}"
        if line not in found:
            found.append(line)
    return found


_DOTTED = re.compile(r"(?<![\d.])\d{4}(?:\.\d{3,6}){3,4}(?!\d)")
_LABELLED = re.compile(r"(?i)\b(cvv2?|cvc2?|cid|pin)\b([^\w\n]{0,3}\s?)(\d{3,6})(?!\d)")
REMOVED = "[removed]"
_FAILED = "[a log line could not be formatted]"


def redact(text: str, secrets: Collection[str] = ()) -> str:
    """Take secrets out of a text. Every digit of every 13 to 19 digit run (spaces, hyphens or
    dots between groups) except the last four becomes X, whether or not it passes the card
    check, because a misread number is still close to a real one. Digits after a cvv, cvc, cid
    or pin label become X, and each of `secrets` (the master password) is replaced."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, REMOVED)
    found = find_numbers(text, allow_test_cards=False, any_long_run=True)
    spans = [(h.start, h.end) for h in found]
    spans += [m.span() for m in _DOTTED.finditer(text)]
    chars = list(text)
    for start, end in _merged_spans(spans):
        positions = [i for i in range(start, end) if chars[i].isdigit()]
        for i in positions[:-4]:
            chars[i] = "X"
    return _LABELLED.sub(lambda m: m[1] + m[2] + "X" * len(m[3]), "".join(chars))


def _merged_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and start < merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(a, b) for a, b in merged]


_SECRET_SOURCES: list[Callable[[], Collection[str]]] = []
_WEAK_SOURCES: list[weakref.WeakMethod[Callable[[], Collection[str]]]] = []
_INSTALLED = False


def register_secret_source(source: Callable[[], Collection[str]]) -> None:
    """Hide what a bound method returns (the master password a gate holds) in every log line,
    whenever redaction is installed. Held weakly, so a gate that is gone is forgotten."""
    _WEAK_SOURCES.append(weakref.WeakMethod(source))


def _current_secrets() -> list[str]:
    found: list[str] = []
    _WEAK_SOURCES[:] = [w for w in _WEAK_SOURCES if w() is not None]
    sources = [*_SECRET_SOURCES, *(m for w in _WEAK_SOURCES if (m := w()) is not None)]
    for source in sources:
        try:
            found.extend(source())
        except Exception:  # a source that fails must not stop a log line
            continue
    return found


def install_log_redaction(secrets: Callable[[], Collection[str]] | None = None) -> None:
    """Redact the final text of every log line, for every handler in the process (also the ones
    added later), including the traceback. Call it once at start-up; `secrets` returns the
    values to hide, such as the master password while the gate holds one. A line that cannot
    be formatted is replaced, never raised. Safe to call again."""
    global _INSTALLED
    if secrets is not None and secrets not in _SECRET_SOURCES:
        _SECRET_SOURCES.append(secrets)
    if _INSTALLED:
        return
    _INSTALLED = True
    original_format = logging.Handler.format

    def format_redacted(self: logging.Handler, record: logging.LogRecord) -> str:
        try:
            text = original_format(self, record)
        except Exception:
            return _FAILED
        return redact(text, _current_secrets())

    logging.Handler.format = format_redacted  # type: ignore[method-assign]


# -- scanning what the app wrote ------------------------------------------------------------------


def _vault_files(vault: VaultRoot) -> list[str]:
    """Every regular file of the vault as a relative path, without following links."""
    found: list[str] = []
    todo = [""]
    while todo:
        folder = todo.pop()
        try:
            entries = vault.list_dir(folder) if folder else vault.list_root()
        except (VaultGone, VaultPathError):
            continue
        for entry in entries:
            rel = f"{folder}/{entry.name}" if folder else entry.name
            if entry.kind == "dir":
                todo.append(rel)
            elif entry.kind == "file":
                found.append(rel)
    return sorted(found)


def _is_secrets_file(rel: str) -> bool:
    return rel == SECRETS_FILE or rel.startswith(f".{SECRETS_FILE}")


def unscanned_files(vault: VaultRoot) -> list[str]:
    """The files `scan_outputs` cannot read as text: photos. They are listed so that the
    owner of the tests knows what a clean scan did not cover."""
    return [
        rel
        for rel in _vault_files(vault)
        if not _is_secrets_file(rel) and Path(rel).suffix.lower() in IMAGE_SUFFIXES
    ]


def _pdf_text(data: bytes) -> str:
    try:
        pages = page_count(data)
    except (LockedPdfError, DamagedFileError):
        return ""
    return "\n".join(ln.text for i in range(pages) for ln in text_layer(data, i)[2])


def _file_text(rel: str, data: bytes) -> str:
    if Path(rel).suffix.lower() == ".pdf":
        return _pdf_text(data)
    return data.decode("utf-8", errors="ignore")


# Columns that hold the text of a card page; there every long digit run counts.
CARD_COLUMNS = frozenset({"items.reading", "items.question", "documents.fields"})
_HEX_TOKEN = re.compile(
    r"\b(?:[0-9a-f]{32,}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b"
)


def _is_card_record(text: str) -> bool:
    return '"doc_type": "card_front"' in text


def _squeeze(text: str) -> str:
    return _SEPARATORS.sub("", text)


def _secret_hits(where: str, text: str, secrets: Collection[str]) -> list[str]:
    flat = _squeeze(text)
    hits: list[str] = []
    for secret in secrets:
        needle = _squeeze(secret)
        if needle and needle in flat:
            if needle.isdigit() and len(needle) > 4:
                hits.append(f"{where}: known secret ending {needle[-4:]}")
            else:
                hits.append(f"{where}: known secret (value not shown)")
    return hits


def _forms(secret: str) -> set[str]:
    """How a known secret can be written: as it is, as digits only, and a card-length number
    grouped 4-4-4-4 (the last group holding the rest) with spaces or with hyphens."""
    forms = {secret}
    digits = "".join(c for c in secret if c.isdigit())
    if digits and all(c.isdigit() or c in " -" for c in secret):
        forms.add(digits)
        if 13 <= len(digits) <= 19:
            groups = [digits[i : i + 4] for i in range(0, len(digits), 4)]
            forms.update({" ".join(groups), "-".join(groups)})
    return {f for f in forms if f}


def _exact_secret_hits(where: str, text: str, secrets: Collection[str]) -> list[str]:
    hits: list[str] = []
    for secret in secrets:
        if any(form in text for form in _forms(secret)):
            digits = "".join(c for c in secret if c.isdigit())
            if len(digits) > 4 and digits and all(c.isdigit() or c in " -" for c in secret):
                hits.append(f"{where}: known secret ending {digits[-4:]}")
            else:
                hits.append(f"{where}: known secret (value not shown)")
    return hits


def _texts_of_database(db_path: Path) -> list[tuple[str, str]]:
    """Every text value of every table, as (table.column, value)."""
    found: list[tuple[str, str]] = []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        tables = [
            r[0]
            for r in conn.execute("select name from sqlite_master where type = 'table'")
            if not str(r[0]).startswith("sqlite_")
        ]
        for table in tables:
            columns = [r[1] for r in conn.execute(f'pragma table_info("{table}")')]
            for column in columns:
                query = f'select "{column}" from "{table}" where typeof("{column}") = ?'
                for (value,) in conn.execute(query, ("text",)):
                    found.append((f"{table}.{column}", value))
    finally:
        conn.close()
    return found


def scan_outputs(
    vault: VaultRoot,
    db_path: Path,
    log_dir: Path,
    known_secrets: Collection[str] = (),
) -> list[str]:
    """Masked hits for every card-shaped or Aadhaar-shaped number (test cards included) and
    every known secret in what the app wrote: each vault file except `Secrets.kdbx` (text
    files as text, PDFs through their text layer; photos are in `unscanned_files`), the
    database file with its write-ahead log as bytes and every text column in it, and every log
    file. Secrets are compared with spaces and hyphens removed."""
    hits: list[str] = []

    def check(where: str, text: str, *, card_text: bool = False) -> None:
        long_run = card_text or (where.startswith(f"{RECORDS}/") and _is_card_record(text))
        # Hash and id tokens go first: a 32-digit hex id holds a run of 12 digits that passes the
        # Aadhaar check now and then (about one id in a hundred), and that is no leak.
        scanned = _HEX_TOKEN.sub("", text)
        hits.extend(
            f"{where}: {d}"
            for d in scan_text(scanned, allow_test_cards=False, any_long_run=long_run)
        )
        if _LABELLED.search(text):
            hits.append(f"{where}: digits after a cvv, cvc, cid or pin label")
        hits.extend(_secret_hits(where, text, known_secrets))

    for rel in _vault_files(vault):
        if _is_secrets_file(rel) or Path(rel).suffix.lower() in IMAGE_SUFFIXES:
            continue
        check(rel, _file_text(rel, vault.read_bytes(rel)))
    for path in (db_path, db_path.with_name(db_path.name + "-wal")):
        if path.is_file():
            # Values sit side by side in the file with nothing between them, so their digits
            # would join into numbers that are not there: only the known secrets are looked for.
            raw = path.read_bytes().decode("latin-1")
            hits.extend(_exact_secret_hits(path.name, raw, known_secrets))
    if db_path.is_file():
        for where, value in _texts_of_database(db_path):
            check(f"{db_path.name}:{where}", value, card_text=where in CARD_COLUMNS)
    if log_dir.is_dir():
        for path in sorted(p for p in log_dir.rglob("*") if p.is_file() and not p.is_symlink()):
            check(path.relative_to(log_dir).as_posix(), path.read_text("utf-8", errors="ignore"))
    return hits
