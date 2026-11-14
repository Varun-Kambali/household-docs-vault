"""How a field's text is compared. Kept apart so the document-type tables and the schemas can
both use it."""

from typing import Literal

FieldKind = Literal[
    "text", "name", "identifier", "aadhaar", "gstin", "address", "date", "amount", "list"
]
