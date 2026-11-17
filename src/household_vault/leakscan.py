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
from collections.abc import Collection
from pathlib import Path

from household_vault.checks import NumberHit, find_numbers
from household_vault.reading.render import DamagedFileError, LockedPdfError, page_count, text_layer
from household_vault.vaultroot import SECRETS_FILE, VaultGone, VaultPathError, VaultRoot

IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".heic", ".heif", ".gif", ".webp", ".tif"})
_LABEL = {"card": "card-shaped", "aadhaar": "Aadhaar-shaped"}
_SEPARATORS = re.compile(r"[\s-]+")


def _masked(digits: str) -> str:
    """All digits but the last four as X."""
    return "X" * max(len(digits) - 4, 0) + digits[-4:]


def scan_text(text: str, *, allow_test_cards: bool) -> list[str]:
    """Masked descriptions of every card-shaped or Aadhaar-shaped number in text, once each.

    With `allow_test_cards` False the networks' published test numbers count too: in the
    synthetic vault they are the secrets.
    """
    found: list[str] = []
    for hit in find_numbers(text, allow_test_cards=allow_test_cards):
        line = f"{_LABEL[hit.kind]} {_masked(hit.digits)}"
        if line not in found:
            found.append(line)
    return found


def _merged(hits: list[NumberHit]) -> list[tuple[int, int]]:
    spans: list[list[int]] = []
    for hit in hits:
        if spans and hit.start < spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], hit.end)
        else:
            spans.append([hit.start, hit.end])
    return [(a, b) for a, b in spans]


def redact(text: str) -> str:
    """Every digit of every card or Aadhaar number except the last four becomes X. Separators
    stay, and overlapping hits are merged first so no window leaves other digits showing."""
    chars = list(text)
    for start, end in _merged(find_numbers(text, allow_test_cards=False)):
        positions = [i for i in range(start, end) if chars[i].isdigit()]
        for i in positions[:-4]:
            chars[i] = "X"
    return "".join(chars)


def install_log_redaction() -> None:
    """Put every log message through `redact`, for every logger in the process. Safe to call
    more than once."""
    previous = logging.getLogRecordFactory()
    if getattr(previous, "redacts", False):
        return

    def factory(*args: object, **kwargs: object) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        record.msg = redact(record.getMessage())
        record.args = None
        return record

    factory.redacts = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)


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

    def check(where: str, text: str) -> None:
        hits.extend(f"{where}: {d}" for d in scan_text(text, allow_test_cards=False))
        hits.extend(_secret_hits(where, text, known_secrets))

    for rel in _vault_files(vault):
        if _is_secrets_file(rel) or Path(rel).suffix.lower() in IMAGE_SUFFIXES:
            continue
        check(rel, _file_text(rel, vault.read_bytes(rel)))
    for path in (db_path, db_path.with_name(db_path.name + "-wal")):
        if path.is_file():
            check(path.name, path.read_bytes().decode("latin-1"))
    if db_path.is_file():
        for where, value in _texts_of_database(db_path):
            check(f"{db_path.name}:{where}", value)
    if log_dir.is_dir():
        for path in sorted(p for p in log_dir.rglob("*") if p.is_file() and not p.is_symlink()):
            check(path.relative_to(log_dir).as_posix(), path.read_text("utf-8", errors="ignore"))
    return hits
