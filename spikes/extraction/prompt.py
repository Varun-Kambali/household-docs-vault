"""Prompt v1 for the extraction spike. The text lives in src and is frozen there."""

from household_vault.reading.prompt import (
    PROMPT_V1,
    ocr_to_text,
    schema_for_prompt,
    schema_json,
    user_prompt,
)

PROMPT_VERSION = PROMPT_V1.version
SYSTEM = PROMPT_V1.system

__all__ = [
    "PROMPT_VERSION",
    "SYSTEM",
    "ocr_to_text",
    "schema_for_prompt",
    "schema_json",
    "user_prompt",
]
