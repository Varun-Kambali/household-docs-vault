import re
from datetime import date

import pytest

from tests.conftest import add_doc

TODAY = date(2026, 11, 20)  # the clock fixture
HEALTH = "h1"
VEHICLE = "v1"


@pytest.fixture
def client(search_client, search_state):
    add_doc(search_state.store, HEALTH, "health_policy", {"end_date": "2026-12-14"}, ["x"])
    add_doc(search_state.store, VEHICLE, "vehicle_policy", {"end_date": "2027-01-31"}, ["x"])
    return search_client


@pytest.fixture
def store(search_state):
    return search_state.store


def coming(client, **params):
    r = client.get("/v1/coming-up", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def renewals(body):
    return [r for r in body["reminders"] if r["rule"] == "policy_renewal"]


def test_coming_up_lists_what_fires_within_the_horizon_in_order(client):
    body = coming(client)
    found = renewals(body)
    assert [r["document_id"] for r in found] == [HEALTH, VEHICLE]
    first = found[0]
    assert first["due"] == "2026-12-14" and first["fire"] == "2026-11-14"
    assert first["custom"] is False and first["part"] is None
    assert first["calendar_link"].startswith("https://calendar.google.com/calendar/render?")
    assert first["person_ids"]
    fires = [r["fire"] for r in body["reminders"]]
    assert fires == sorted(fires)
    assert body["count_due_now"] == sum(f <= TODAY.isoformat() for f in fires) >= 1
    short = coming(client, days=7)
    assert [r["document_id"] for r in renewals(short)] == [HEALTH]
    assert client.get("/v1/coming-up", params={"days": 0}).status_code == 422
    assert client.get("/v1/coming-up", params={"days": 366}).status_code == 422


def test_a_reminder_without_a_calendar_entry_has_no_link(client):
    premium = [r for r in coming(client)["reminders"] if r["rule"] == "premium_due"]
    assert all(r["calendar_link"] is None for r in premium)


def test_done_is_keyed_to_the_due_date(client, store):
    key = renewals(coming(client))[0]["key"]
    assert client.post(f"/v1/reminders/{key}/done").status_code == 204
    assert HEALTH not in [r["document_id"] for r in renewals(coming(client))]
    # the renewal files with a new end date: a new key, so it reminds again
    store.conn.execute(
        "update documents set fields = ? where id = ?", ('{"end_date": "2027-12-14"}', HEALTH)
    )
    store.conn.commit()
    again = [r for r in renewals(coming(client, days=365)) if r["document_id"] == HEALTH]
    assert again and again[0]["due"] == "2027-12-14" and again[0]["key"] != key
    assert client.delete(f"/v1/reminders/{key}/state").status_code == 204


def test_undo_brings_a_done_reminder_back(client):
    key = renewals(coming(client))[0]["key"]
    client.post(f"/v1/reminders/{key}/done")
    assert client.delete(f"/v1/reminders/{key}/state").status_code == 204
    assert key in [r["key"] for r in coming(client)["reminders"]]


def test_snooze_hides_until_its_date(client, clock):
    key = renewals(coming(client))[0]["key"]
    r = client.post(f"/v1/reminders/{key}/snooze", json={"until": "2026-11-25"})
    assert r.status_code == 204
    assert key not in [x["key"] for x in coming(client)["reminders"]]
    clock.advance(5 * 86400)
    assert key in [x["key"] for x in coming(client)["reminders"]]
    clock.advance(-5 * 86400)
    for bad in ("2026-11-20", "2026-11-19", "2027-11-21", "soon"):
        assert client.post(f"/v1/reminders/{key}/snooze", json={"until": bad}).status_code == 422
    assert (
        client.post(f"/v1/reminders/{key}/snooze", json={"until": "2026-11-21"}).status_code == 204
    )
    assert (
        client.post(f"/v1/reminders/{key}/snooze", json={"until": "2027-11-20"}).status_code == 204
    )


def test_an_unknown_key_is_a_404(client):
    for call in (
        lambda k: client.post(f"/v1/reminders/{k}/done"),
        lambda k: client.post(f"/v1/reminders/{k}/snooze", json={"until": "2026-11-25"}),
        lambda k: client.delete(f"/v1/reminders/{k}/state"),
    ):
        assert call("nope:policy_renewal::2026-12-14").status_code == 404
    assert client.delete("/v1/reminders/custom/999").status_code == 404


def test_remind_me_adds_a_reminder_that_coming_up_shows(client):
    r = client.post("/v1/reminders", json={"document_id": HEALTH, "due": "2026-12-01"})
    assert r.status_code == 200, r.text
    made = r.json()
    assert made["custom"] is True and made["rule"] == "custom" and made["document_id"] == HEALTH
    assert made["due"] == made["fire"] == "2026-12-01"
    assert made["title"].startswith("Remember ") and not re.search(r"\d{4,}", made["title"])
    assert made["calendar_link"].startswith("https://calendar.google.com/calendar/render?")
    assert made["key"] in [x["key"] for x in coming(client)["reminders"]]
    assert (
        client.post("/v1/reminders", json={"document_id": "nope", "due": "2026-12-01"}).status_code
        == 404
    )
    done = client.post(f"/v1/reminders/{made['key']}/done")
    assert done.status_code == 204
    cid = made["key"].rsplit(":c", 1)[1]
    assert client.delete(f"/v1/reminders/custom/{cid}").status_code == 204
    assert made["key"] not in [x["key"] for x in coming(client)["reminders"]]
    assert client.delete(f"/v1/reminders/custom/{cid}").status_code == 404


def test_remind_me_dates_are_bounded(client):
    for due in ("2026-11-19", "2028-11-20", "tomorrow"):
        r = client.post("/v1/reminders", json={"document_id": HEALTH, "due": due})
        assert r.status_code == 422


def test_reminder_settings_read_defaults_then_what_was_saved(client):
    got = client.get("/v1/settings/reminders").json()
    assert got["horizon_days"] == 60
    assert got["leads"]["policy_renewal"] == [{"days": 60}, {"days": 30}, {"days": 7}]
    assert got["leads"]["passport_expiry"] == [{"months": 9}]
    body = {"leads": {"policy_renewal": [{"days": 14}, {"months": 2}]}, "horizon_days": 90}
    put = client.put("/v1/settings/reminders", json=body)
    assert put.status_code == 200
    assert put.json()["leads"]["policy_renewal"] == [{"days": 14}, {"months": 2}]
    assert put.json()["leads"]["passport_expiry"] == [{"months": 9}]
    assert client.get("/v1/settings/reminders").json() == put.json()
    fires = [r["fire"] for r in renewals(coming(client))]
    assert "2026-11-30" in fires  # 14 days before 14 Dec: the settings reach the list


def test_reminder_settings_are_bounded(client):
    def put(leads, horizon=60):
        return client.put("/v1/settings/reminders", json={"leads": leads, "horizon_days": horizon})

    assert put({"policy_renewal": [{"days": 401}]}).status_code == 422
    assert put({"policy_renewal": [{"days": -1}]}).status_code == 422
    assert put({"policy_renewal": [{"months": 25}]}).status_code == 422
    assert put({"policy_renewal": [{"days": 5, "months": 1}]}).status_code == 422
    assert put({"policy_renewal": [{}]}).status_code == 422
    assert put({"policy_renewal": []}).status_code == 422
    assert put({}, horizon=0).status_code == 422
    assert put({}, horizon=6).status_code == 422
    assert put({}, horizon=366).status_code == 422
    bad = put({"nope": [{"days": 3}]})
    assert bad.status_code == 422 and "nope" in bad.json()["detail"]
    named = put({"policy_renewal": [{"days": 401}]})
    assert "policy_renewal" in str(named.json())
    assert (
        put({"policy_renewal": [{"days": 400}, {"months": 24}, {"days": 0}]}, 365).status_code
        == 200
    )
    assert put({}, horizon=7).status_code == 200


def test_the_routes_carry_no_card_photo_or_file_path(client):
    body = str(coming(client))
    assert "rel_path" not in body and "/Users" not in body


def remind_on(client, due):
    r = client.post("/v1/reminders", json={"document_id": HEALTH, "due": due})
    assert r.status_code == 200, r.text
    return r.json()["key"]


def test_the_saved_horizon_is_stored_and_used_by_coming_up(client):
    near = remind_on(client, "2027-02-08")  # 80 days out
    far = remind_on(client, "2027-02-28")  # 100 days out
    keys = [r["key"] for r in coming(client)["reminders"]]
    assert near not in keys and far not in keys  # the default horizon is 60 days
    put = client.put("/v1/settings/reminders", json={"leads": {}, "horizon_days": 90})
    assert put.status_code == 200
    assert put.json()["horizon_days"] == 90
    assert client.get("/v1/settings/reminders").json()["horizon_days"] == 90
    keys = [r["key"] for r in coming(client)["reminders"]]
    assert near in keys and far not in keys


def test_removing_a_document_drops_its_reminder_state(client, store):
    key = renewals(coming(client))[0]["key"]
    assert key.startswith(f"{HEALTH}:")
    client.post(f"/v1/reminders/{key}/done")
    other = renewals(coming(client))[0]["key"]
    client.post(f"/v1/reminders/{other}/done")
    assert key in store.reminder_states() and other in store.reminder_states()
    store.remove_document(HEALTH)
    assert key not in store.reminder_states()
    assert other in store.reminder_states()
    assert client.post(f"/v1/reminders/{key}/done").status_code == 404


def test_remind_me_on_a_document_removed_mid_request_is_a_404(client, store, monkeypatch):
    real = store.add_custom_reminder

    def racing(doc_id, due, title):
        store.remove_document(doc_id)
        return real(doc_id, due, title)

    monkeypatch.setattr(store, "add_custom_reminder", racing)
    r = client.post("/v1/reminders", json={"document_id": HEALTH, "due": "2026-12-01"})
    assert r.status_code == 404
    assert r.json()["detail"] == "That document is not in the vault."
