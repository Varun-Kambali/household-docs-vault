"""Check one file in the vault: what it is, and whether it can be read and is new."""

import hashlib
import io
from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import Literal

from PIL import Image

from household_vault.db import Store
from household_vault.intake.sniff import FileKind, sniff
from household_vault.reading.render import DamagedFileError, LockedPdfError, page_count
from household_vault.vaultroot import VaultRoot

Outcome = Literal["ok", "empty", "unsupported", "damaged", "locked", "duplicate"]

_HEAD = 64


@dataclass(frozen=True)
class CheckResult:
    outcome: Outcome
    kind: FileKind | None
    sha256: str
    size: int
    pages: int | None
    duplicate_of: str | None


def _duplicate_of(
    store: Store, sha: str, rel: str, seen: MutableMapping[str, str], item_id: int | None
) -> str | None:
    filed = store.filed_with_sha(sha)
    if filed:
        return filed[0].rel_path
    for other in store.items_with_sha(sha, ["asked"]):
        if other.id != item_id:
            return other.rel_path or other.original_name
    earlier = seen.get(sha)
    if earlier is not None and earlier != rel:
        return earlier
    return None


def _opens(kind: FileKind, data: bytes) -> tuple[Outcome, int | None]:
    if kind is FileKind.pdf:
        try:
            return "ok", page_count(data)
        except LockedPdfError:
            return "locked", None
        except DamagedFileError:
            return "damaged", None
    try:
        # verify() checks structure only; load() decodes every pixel, which catches a file cut
        # short by a half-finished sync. LOAD_TRUNCATED_IMAGES stays False.
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.load()
    except Exception:  # Pillow raises several types for a bad image
        return "damaged", None
    return "ok", None


def check_file(
    vault: VaultRoot,
    rel: str,
    store: Store,
    seen_in_pass: MutableMapping[str, str],
    *,
    item_id: int | None,
    skip_duplicate: bool = False,
) -> CheckResult:
    """Check rel. A file that vanishes raises VaultGone; the caller records it as gone."""

    def result(
        outcome: Outcome,
        kind: FileKind | None,
        sha: str,
        size: int,
        pages: int | None = None,
        dup: str | None = None,
    ) -> CheckResult:
        return CheckResult(outcome, kind, sha, size, pages, dup)

    head, size = vault.head_and_size(rel, _HEAD)
    if size == 0:
        return result("empty", None, hashlib.sha256(b"").hexdigest(), 0)
    kind = sniff(head)
    # A file that is opened is read once and hashed from those bytes, so the checked bytes
    # and the recorded hash cannot differ if the file changes underneath.
    data: bytes | None = None
    if kind in (FileKind.pdf, FileKind.jpeg, FileKind.png):
        data = vault.read_bytes(rel)
        size = len(data)
        sha = hashlib.sha256(data).hexdigest()
    else:
        sha, size = vault.hash_and_size(rel)
    if kind is None:
        return result("unsupported", None, sha, size)
    if not skip_duplicate:
        dup = _duplicate_of(store, sha, rel, seen_in_pass, item_id)
        if dup is not None:
            return result("duplicate", kind, sha, size, dup=dup)
    pages: int | None = None
    if data is not None:
        outcome, pages = _opens(kind, data)
        if outcome != "ok":
            return result(outcome, kind, sha, size)
    seen_in_pass.setdefault(sha, rel)
    return result("ok", kind, sha, size, pages)
