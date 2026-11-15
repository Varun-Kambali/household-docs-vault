"""What the reader is given: one file's bytes, or in-memory uploads, and the key they share."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

from household_vault.intake.sniff import FileKind


@dataclass(frozen=True)
class DocumentSource:
    """`data` is a whole file read through VaultRoot. `images` are in-memory uploads (one per
    page, all of `kind`), which never touch the disk."""

    kind: FileKind
    data: bytes | None = None
    images: list[bytes] | None = None


def document_key(files: Sequence[bytes]) -> str:
    """The SHA-256 of one file, or of the joined SHA-256s of several."""
    digests = [hashlib.sha256(f).hexdigest() for f in files]
    if len(digests) == 1:
        return digests[0]
    return hashlib.sha256("".join(digests).encode()).hexdigest()
