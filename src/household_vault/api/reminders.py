"""Reminder routes. Reminders are worked out from the stored fields on every read; only a
reminder's state (done or snoozed), the ones made by Remind me and the lead settings are stored.
Nothing is sent anywhere: a calendar link is a URL the person opens themselves.
"""

import json
from datetime import date, timedelta
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Response

from household_vault.api.models import (
    ComingUpOut,
    LeadIn,
    ReminderOut,
    ReminderSettingsIn,
    ReminderSettingsOut,
    RemindMeIn,
    SnoozeIn,
)
from household_vault.app_state import AppState
from household_vault.reminders.calendar import calendar_link, title_of
from household_vault.reminders.compute import (
    HORIZON_KEY,
    LEADS_KEY,
    Reminder,
    ReminderSettings,
    custom_key,
    load_settings,
    reminders,
)
from household_vault.reminders.rules import RULES, RULES_BY_NAME, Days, Lead, Rule

NO_REMINDER = "That reminder is not there."
NO_DOCUMENT = "That document is not in the vault."
BAD_SNOOZE = "A reminder can be snoozed from tomorrow to one year from today."
BAD_DUE = "A reminder can be set from today to one year from today."
MAX_AHEAD_DAYS = 365

# Remind me has no rule of its own; it borrows the shape of one for its title.
CUSTOM_RULE = Rule("custom", frozenset(), "", (), True, "Remember")


def lead_out(lead: Lead) -> LeadIn:
    return LeadIn(days=lead.n) if isinstance(lead, Days) else LeadIn(months=lead.n)


def lead_text(lead: LeadIn) -> str:
    return f"{lead.days}d" if lead.days is not None else f"{lead.months}m"


def settings_out(settings: ReminderSettings) -> ReminderSettingsOut:
    return ReminderSettingsOut(
        leads={r.name: [lead_out(x) for x in settings.leads_for(r.name)] for r in RULES},
        horizon_days=settings.horizon_days,
    )


def reminder_out(r: Reminder) -> ReminderOut:
    return ReminderOut(
        key=r.key,
        rule=r.rule,
        document_id=r.document_id,
        person_ids=list(r.person_ids),
        title=r.title,
        due=r.due,
        fire=r.fire,
        part=r.part,
        calendar_link=calendar_link(r),
        custom=r.custom,
    )


def add_reminder_routes(app: FastAPI, state: AppState) -> None:
    store = state.store

    def today() -> date:
        return state.worker.clock().date()

    def known(key: str) -> None:
        """A key is known when the list shows it now, it has a state, or it is a custom one."""
        if key in store.reminder_states():
            return
        if key in {custom_key(c.document_id, c.due, c.id) for c in store.custom_reminders()}:
            return
        if key in {r.key for r in reminders(store, today(), load_settings(store))}:
            return
        raise HTTPException(404, NO_REMINDER)

    @app.get("/v1/coming-up")
    def coming_up(
        days: Annotated[int | None, Query(ge=1, le=MAX_AHEAD_DAYS)] = None,
    ) -> ComingUpOut:
        settings = load_settings(store)
        if days is not None:
            settings = ReminderSettings(settings.leads, days)
        now = today()
        found = reminders(store, now, settings)
        return ComingUpOut(
            reminders=[reminder_out(r) for r in found],
            count_due_now=sum(r.fire <= now for r in found),
        )

    @app.post("/v1/reminders/{key}/done", status_code=204)
    def done(key: str) -> Response:
        known(key)
        store.set_reminder_state(key, "done", None)
        return Response(status_code=204)

    @app.post("/v1/reminders/{key}/snooze", status_code=204)
    def snooze(key: str, body: SnoozeIn) -> Response:
        known(key)
        now = today()
        if not now + timedelta(days=1) <= body.until <= now + timedelta(days=MAX_AHEAD_DAYS):
            raise HTTPException(422, BAD_SNOOZE)
        store.set_reminder_state(key, "snoozed", body.until)
        return Response(status_code=204)

    @app.delete("/v1/reminders/{key}/state", status_code=204)
    def clear_state(key: str) -> Response:
        known(key)
        store.clear_reminder_state(key)
        return Response(status_code=204)

    @app.post("/v1/reminders")
    def remind_me(body: RemindMeIn) -> ReminderOut:
        doc = store.document(body.document_id)
        if doc is None:
            raise HTTPException(404, NO_DOCUMENT)
        now = today()
        if not now <= body.due <= now + timedelta(days=MAX_AHEAD_DAYS):
            raise HTTPException(422, BAD_DUE)
        title = title_of(CUSTOM_RULE, doc, None)
        new_id = store.add_custom_reminder(doc.id, body.due, title)
        people = tuple(person for person, _role in store.people_of(doc.id))
        return reminder_out(
            Reminder(
                custom_key(doc.id, body.due, new_id),
                "custom",
                doc.id,
                people,
                title,
                body.due,
                body.due,
                None,
                True,
                True,
            )
        )

    @app.delete("/v1/reminders/custom/{reminder_id}", status_code=204)
    def remove_custom(reminder_id: int) -> Response:
        found = [c for c in store.custom_reminders() if c.id == reminder_id]
        if not found:
            raise HTTPException(404, NO_REMINDER)
        c = found[0]
        store.remove_custom_reminder(reminder_id)
        store.clear_reminder_state(custom_key(c.document_id, c.due, c.id))
        return Response(status_code=204)

    @app.get("/v1/settings/reminders", response_model_exclude_none=True)
    def get_settings() -> ReminderSettingsOut:
        return settings_out(load_settings(store))

    @app.put("/v1/settings/reminders", response_model_exclude_none=True)
    def put_settings(body: ReminderSettingsIn) -> ReminderSettingsOut:
        unknown = sorted(name for name in body.leads if name not in RULES_BY_NAME)
        if unknown:
            raise HTTPException(422, f"There is no reminder rule called {unknown[0]}.")
        stored = {name: [lead_text(x) for x in leads] for name, leads in body.leads.items()}
        store.set_setting(LEADS_KEY, json.dumps(stored))
        store.set_setting(HORIZON_KEY, str(body.horizon_days))
        return settings_out(load_settings(store))
