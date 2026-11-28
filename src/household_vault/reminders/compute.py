"""Reminders for the documents filed now. Nothing is stored but each reminder's state."""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from household_vault.db import DocumentRow, Store
from household_vault.periods import card_expiry_end, part_end
from household_vault.reminders.calendar import title_of
from household_vault.reminders.rules import (
    RULES,
    RULES_BY_NAME,
    Days,
    Lead,
    Months,
    Rule,
    fire_date,
)
from household_vault.schemas._coerce import parse_amount, parse_date
from household_vault.search.vocab import DATE_ROLES

log = logging.getLogger(__name__)

PAST_DAYS = 30
_LEAD = re.compile(r"([0-9]{1,3})([dm])")


@dataclass(frozen=True)
class Reminder:
    key: str
    rule: str
    document_id: str
    person_ids: tuple[str, ...]
    title: str
    due: date
    fire: date
    part: str | None
    calendar: bool
    custom: bool


@dataclass(frozen=True)
class ReminderSettings:
    leads: dict[str, tuple[Lead, ...]] = field(default_factory=dict)
    horizon_days: int = 60

    def leads_for(self, rule: str) -> tuple[Lead, ...]:
        return self.leads.get(rule, RULES_BY_NAME[rule].leads)


def _parse_leads(raw: object) -> tuple[Lead, ...] | None:
    if not isinstance(raw, list) or not raw:
        return None
    leads: list[Lead] = []
    for item in raw:
        m = _LEAD.fullmatch(item) if isinstance(item, str) else None
        if m is None or int(m[1]) == 0:
            return None
        leads.append((Days if m[2] == "d" else Months)(int(m[1])))
    return tuple(leads)


def load_settings(store: Store) -> ReminderSettings:
    """The `reminder_leads` setting, a JSON object of rule name to lead strings like
    "60d" or "9m". A rule that is missing or unreadable keeps its default."""
    try:
        data: Any = json.loads(store.setting("reminder_leads") or "{}")
    except ValueError:
        log.warning("reminder_leads is not JSON; using the defaults")
        return ReminderSettings()
    leads: dict[str, tuple[Lead, ...]] = {}
    if isinstance(data, dict):
        for name, raw in data.items():
            parsed = _parse_leads(raw)
            if name in RULES_BY_NAME and parsed is not None:
                leads[name] = parsed
    return ReminderSettings(leads)


def _as_date(value: object) -> date | None:
    try:
        return parse_date(value)
    except ValueError:
        return None


def _dues(rule: Rule, doc: DocumentRow) -> list[tuple[date, str | None]]:
    """The (due date, part) pairs a document has for a rule; none when a date is unreadable."""
    if rule.date == "warranty_parts":
        start = _as_date(doc.fields.get("purchase_date"))
        parts = doc.fields.get("warranty_parts")
        if start is None or not isinstance(parts, list):
            return []
        out: list[tuple[date, str | None]] = []
        for item in parts:
            if not isinstance(item, dict) or not isinstance(item.get("part"), str):
                continue
            try:
                years = parse_amount(item.get("years"))
            except (ValueError, InvalidOperation):
                continue
            try:
                out.append((part_end(start, Decimal(years)), item["part"]))
            except (ValueError, OverflowError):
                continue
        return out
    if rule.date == "card_expiry":
        end = card_expiry_end(doc.fields.get("expiry"))  # type: ignore[arg-type]
        return [] if end is None else [(end, None)]
    name = DATE_ROLES[doc.doc_type].get(rule.date)  # type: ignore[call-overload]
    day = _as_date(doc.fields.get(name)) if name else None
    return [] if day is None else [(day, None)]


def _people(store: Store, doc_id: str) -> tuple[str, ...]:
    return tuple(person for person, _role in store.people_of(doc_id))


def reminders(store: Store, today: date, settings: ReminderSettings) -> list[Reminder]:
    """Every reminder due to show: its fire day is on or before today plus the horizon, and its
    due date is at most 30 days past. Done ones are dropped, snoozed ones until their day."""
    states = store.reminder_states()
    horizon = today + timedelta(days=settings.horizon_days)
    oldest = today - timedelta(days=PAST_DAYS)
    found: list[Reminder] = []

    def hidden(key: str) -> bool:
        state = states.get(key)
        if state is None:
            return False
        if state.state == "snoozed":
            return state.until is not None and today < state.until
        return True

    def fire_for(due: date, leads: tuple[Lead, ...]) -> date | None:
        """The latest lead already reached, else the next one inside the horizon."""
        fires: list[date] = []
        for lead in leads:
            try:
                fires.append(fire_date(due, lead))
            except (ValueError, OverflowError):
                continue
        reached = [f for f in fires if f <= today]
        if reached:
            return max(reached)
        ahead = [f for f in fires if f <= horizon]
        return min(ahead) if ahead else None

    for rule in RULES:
        leads = settings.leads_for(rule.name)
        for doc_type in sorted(rule.types, key=lambda t: t.value):
            for doc in store.documents_of_type(doc_type):
                for due, part in _dues(rule, doc):
                    key = f"{doc.id}:{rule.name}:{part or ''}:{due.isoformat()}"
                    if due < oldest or hidden(key):
                        continue
                    fire = fire_for(due, leads)
                    if fire is not None:
                        found.append(
                            Reminder(
                                key, rule.name, doc.id, _people(store, doc.id),
                                title_of(rule, doc, part), due, fire, part, rule.calendar,
                                False,
                            )
                        )  # fmt: skip
    for c in store.custom_reminders():
        key = f"{c.document_id}:custom::{c.due.isoformat()}:c{c.id}"
        if c.due >= oldest and c.due <= horizon and not hidden(key):
            found.append(
                Reminder(key, "custom", c.document_id, _people(store, c.document_id), c.title,
                         c.due, c.due, None, False, True)
            )  # fmt: skip
    found.sort(key=lambda r: (r.fire, r.due, r.key))
    return found
