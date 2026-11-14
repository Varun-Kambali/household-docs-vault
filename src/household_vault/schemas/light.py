"""The small schemas for the light document types, built from `LIGHT_FIELDS`."""

from functools import cache
from typing import Any

from pydantic import BaseModel, Field, create_model

from household_vault.doctypes import LIGHT_FIELDS, DocType
from household_vault.schemas._coerce import (
    Amount,
    FieldKind,
    FlexDate,
    Identifier,
    Name,
    Text,
)

_KIND_TYPES: dict[FieldKind, Any] = {
    "text": Text,
    "identifier": Identifier,
    "amount": Amount,
}


@cache
def light_schema(doc_type: DocType) -> type[BaseModel]:
    fields: dict[str, Any] = {
        "person_name": (Name | None, None),
        "document_date": (FlexDate | None, None),
        "expiry_date": (
            FlexDate | None,
            Field(default=None, description="expiry, renewal or due date"),
        ),
    }
    for name, kind in LIGHT_FIELDS[doc_type]:
        fields[name] = (_KIND_TYPES[kind] | None, None)
    return create_model(f"Light_{doc_type.value}", **fields)
