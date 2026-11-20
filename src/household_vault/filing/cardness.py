"""Which items hold a card photo that has to stay out of the vault's served and moved files."""

from __future__ import annotations

from household_vault.db import CARD_MARK, Item, ItemState, Store
from household_vault.doctypes import DocType
from household_vault.reasons import Reason

# Every state in which an item can still hold its file.
CARD_STATES: tuple[ItemState, ...] = (
    "queued",
    "reading",
    "filing",
    "filed_pending_clear",
    "undoing",
    "moving",
    "asked",
    "held",
    "waiting_secrets",
)


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


def shares_card_photo(store: Store, item: Item) -> bool:
    """True for a card item, or an item with the same bytes as one (a copy of the photo)."""
    if is_card_item(item):
        return True
    return any(is_card_item(other) for other in store.items_with_sha(item.sha256, CARD_STATES))
