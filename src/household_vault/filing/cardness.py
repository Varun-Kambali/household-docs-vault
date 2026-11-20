"""Which items hold a card photo that has to stay out of the vault's served and moved files."""

from __future__ import annotations

from household_vault.db import CARD_MARK, Item, Store
from household_vault.doctypes import DocType
from household_vault.reasons import Reason


def is_card_item(item: Item) -> bool:
    """A card photo: read or typed as a card front, waiting for the secrets store, or asked
    because its number could not be read."""
    stored = (item.reading or {}).get("doc_type")
    return (
        DocType.card_front.value in (stored, item.overrides.get("doc_type"))
        or bool(item.overrides.get(CARD_MARK))
        or item.state == "waiting_secrets"
        or Reason.card_unreadable in item.reasons
    )


def is_card_photo(store: Store, sha256: str) -> bool:
    """The one gate: these bytes were, in any item and any state, a card photo. Every route that
    serves, moves or files a file's raw bytes asks it. The masked copy of a card has its own
    SHA-256, so it passes."""
    return store.is_card_sha(sha256)


def shares_card_photo(store: Store, item: Item) -> bool:
    """True for a card item, or an item whose bytes were ever a card photo."""
    return is_card_item(item) or is_card_photo(store, item.sha256)


def mark_card(store: Store, item: Item) -> None:
    """Mark an item (a copy of a card photo) as a card, for good."""
    if not item.overrides.get(CARD_MARK):
        store.update_item(item.id, overrides={**item.overrides, CARD_MARK: True})
