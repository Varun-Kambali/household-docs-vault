"""Why a file is held in Needs a look. The order is the order the app asks about them."""

from enum import StrEnum


class Reason(StrEnum):
    locked = "locked"
    unsupported_type = "unsupported_type"
    empty_file = "empty_file"
    damaged = "damaged"
    duplicate = "duplicate"
    recording = "recording"
    copy_mismatch = "copy_mismatch"
    read_failed = "read_failed"
    no_english = "no_english"
    type_unsure = "type_unsure"
    card_unreadable = "card_unreadable"
    person_unknown = "person_unknown"
    person_unsure = "person_unsure"
    missing_required = "missing_required"
    field_issue = "field_issue"
    possible_copy = "possible_copy"


PRIORITY: tuple[Reason, ...] = (
    Reason.locked,
    Reason.unsupported_type,
    Reason.empty_file,
    Reason.damaged,
    Reason.duplicate,
    Reason.recording,
    Reason.copy_mismatch,
    Reason.read_failed,
    Reason.no_english,
    Reason.type_unsure,
    Reason.card_unreadable,
    Reason.person_unknown,
    Reason.person_unsure,
    Reason.missing_required,
    Reason.field_issue,
    Reason.possible_copy,
)
