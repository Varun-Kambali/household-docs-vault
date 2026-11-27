import json
import logging
from datetime import date

from household_vault.doctypes import DocType
from household_vault.search.query import Query
from tests.unit.api.conftest import FIND


def a_list_query() -> dict:
    return Query(intent="list", people=["p1"], types=[DocType.health_policy]).model_dump(
        mode="json"
    )


def post(client, prompt, full=True):
    return client.post("/v1/search", json={"prompt": prompt, "full": full})


def test_search_caps_and_accepts_any_prompt(search_client):  # Review Focus 11
    for prompt in ['"', "AND", "NEAR(", "\U0001f642", "x" * 300]:
        assert post(search_client, prompt).status_code == 200
    assert post(search_client, "x" * 301).status_code == 422
    assert post(search_client, "   ").status_code == 422
    assert post(search_client, " " * 400 + "ok").status_code == 200  # the cap is after trimming


def test_an_invalid_prompt_is_not_echoed(search_client):
    r = post(search_client, "SECRET-WORDS" * 40)
    assert r.status_code == 422 and "SECRET-WORDS" not in r.text


def test_search_without_models_falls_back_to_keywords(client_without_ollama):  # Review Focus 13
    out = post(client_without_ollama, "Croma").json()
    assert (out["reading"], out["vectors"]) == ("off", "off") and out["rows"]
    assert out["query"] is None and out["sentence"] is None and out["answer"] is None


def test_a_quick_search_runs_no_model(search_client, spy_reader):
    out = post(search_client, "Croma", full=False).json()
    assert spy_reader.calls == 0 and out["rows"]
    assert (out["reading"], out["vectors"]) == ("on", "on")
    assert out["query"] is None and out["sentence"] is None


def test_a_full_search_reads_the_prompt(search_client, spy_reader):
    out = post(search_client, "Croma").json()
    assert spy_reader.calls == 1 and out["reading"] == "on"
    assert out["query"]["intent"] == "find" and out["query"]["words"] == "Croma"
    assert out["sentence"] is None and out["answer"] is None and out["no_answer"] is None
    assert out["rows"] and out["rows"][0]["drive_path"].startswith("My Drive/Family Vault/")


def test_a_list_prompt_returns_rows_with_their_sentence(search_client, spy_reader):
    spy_reader.answers["health policies"] = json.dumps(
        {**FIND, "intent": "list", "types": ["health_policy"]}
    )
    out = post(search_client, "health policies").json()
    assert [p["slot"] for p in out["sentence"]["parts"]] == ["what", "who", "verb", "when"]
    assert out["sentence"]["text"].startswith("Showing health insurance policies for everyone")
    assert {r["doc_type"] for r in out["rows"]} == {"health_policy"}


def test_a_stale_vector_index_is_reported(search_client, search_state):
    search_state.store.conn.execute(
        "update meta set value = 'other-model' where key = 'embed_model'"
    )
    assert post(search_client, "Croma", full=False).json()["vectors"] == "stale"


def test_a_lookup_answers_from_a_field_with_a_located_line(search_client, spy_reader):
    spy_reader.answers["when was the Croma invoice"] = json.dumps(
        {
            **FIND,
            "intent": "lookup",
            "types": ["tax_invoice"],
            "field": "invoice_date",
            "words": "Croma",
        }
    )
    out = post(search_client, "when was the Croma invoice").json()
    assert (out["answer"] is None) != (out["no_answer"] is None)
    assert out["answer"] is not None, out["no_answer"]
    assert out["answer"]["field"] == "invoice_date" and out["answer"]["lines"]
    assert out["answer"]["document_id"] == out["rows"][0]["document_id"]
    assert out["sentence"] is None or out["sentence"]["parts"]


def test_list_changes_never_call_the_model(search_client, spy_reader):
    r = search_client.post(
        "/v1/search/list",
        json={"query": a_list_query(), "change": {"slot": "who", "value": "p2"}},
    )
    assert r.status_code == 200 and spy_reader.calls == 0
    body = r.json()
    assert body["query"]["people"] == ["p2"]
    who = next(p for p in body["sentence"]["parts"] if p["slot"] == "who")
    assert who["text"] == "Kavita Rao" or who["value"] == ["p2"]


def test_a_list_without_a_change_returns_the_rows(search_client):
    r = search_client.post("/v1/search/list", json={"query": a_list_query()})
    assert r.status_code == 200
    assert {row["doc_type"] for row in r.json()["rows"]} <= {"health_policy"}


def test_a_change_the_sentence_does_not_offer_is_a_422(search_client):
    r = search_client.post(
        "/v1/search/list",
        json={"query": a_list_query(), "change": {"slot": "when", "value": "someday"}},
    )
    assert r.status_code == 422
    r = search_client.post(
        "/v1/search/list", json={"query": a_list_query(), "change": {"slot": "nope", "value": 1}}
    )
    assert r.status_code == 422


def test_today_comes_from_the_apps_clock(search_client, clock):
    clock.set(clock().replace(year=2030, month=3, day=10))
    r = search_client.post(
        "/v1/search/list",
        json={"query": a_list_query(), "change": {"slot": "when", "value": "this_year"}},
    )
    assert r.json()["query"]["range"] == {"start": "2030-01-01", "end": "2030-12-31"}
    assert date(2030, 4, 1).isoformat() in json.dumps(r.json()["sentence"])


def test_a_search_from_another_site_is_refused(search_client):
    r = search_client.post(
        "/v1/search", json={"prompt": "Croma"}, headers={"Origin": "http://evil.example"}
    )
    assert r.status_code == 403


def test_the_prompt_is_never_logged_or_stored(search_client, search_state, caplog):
    caplog.set_level(logging.DEBUG)
    post(search_client, "PAN ABCDE1234F")
    post(search_client, "PAN ABCDE1234F", full=False)
    assert "ABCDE1234F" not in caplog.text
    with search_state.store.lock:
        names = [
            r[0]
            for r in search_state.store.conn.execute(
                "select name from sqlite_master where type = 'table'"
            )
        ]
        for name in names:
            if name.startswith("sqlite_"):
                continue
            for row in search_state.store.conn.execute(f'select * from "{name}"'):
                assert "ABCDE1234F" not in repr(tuple(row))


def test_rows_and_documents_carry_the_drive_path(search_client, filed_ids):
    doc = search_client.get(f"/v1/documents/{filed_ids[0]}").json()
    assert doc["drive_path"] == f"My Drive/Family Vault/{doc['rel_path']}"
    assert doc["page_count"] >= 1 and isinstance(doc["people"], list)
    assert isinstance(doc["field_kinds"], dict) and set(doc["field_kinds"]) >= set(doc["fields"])


def test_people_lists_the_household(search_client):
    people = search_client.get("/v1/people").json()
    assert {"id": "p1", "name": "Ravi Kumar Rao"} in people and len(people) >= 4


def test_the_prompt_text_fills_a_person_the_model_left_out(search_client):
    out = post(search_client, "Kavita Rao policies").json()
    assert out["query"]["people"] == ["p2"]


def test_rows_carry_the_kind_of_each_key_field(search_client):
    rows = post(search_client, "Croma", full=False).json()["rows"]
    assert rows
    for row in rows:
        assert set(row["field_kinds"]) >= set(row["key_fields"])


CROMA_LOOKUP = {
    **FIND,
    "intent": "lookup",
    "types": ["tax_invoice"],
    "field": "invoice_date",
    "words": "Croma",
}


def test_a_lookup_returns_its_reading_sentence(search_client, spy_reader):
    spy_reader.answers["when was the Croma invoice"] = json.dumps(CROMA_LOOKUP)
    out = post(search_client, "when was the Croma invoice").json()
    assert [p["slot"] for p in out["sentence"]["parts"]][:2] == ["what", "who"]
    assert out["sentence"]["text"].startswith("Showing ")


def test_changing_a_lookup_part_reruns_it_without_the_model(search_client, spy_reader):
    spy_reader.answers["when was the Croma invoice"] = json.dumps(CROMA_LOOKUP)
    first = post(search_client, "when was the Croma invoice").json()
    calls = spy_reader.calls
    r = search_client.post(
        "/v1/search",
        json={
            "prompt": "when was the Croma invoice",
            "full": True,
            "query": first["query"],
            "change": {"slot": "who", "value": "p2"},
        },
    )
    assert r.status_code == 200 and spy_reader.calls == calls
    out = r.json()
    assert out["query"]["people"] == ["p2"] and out["query"]["intent"] == "lookup"
    assert out["sentence"] is not None
    assert out["answer"] is not None or out["no_answer"] is not None


def test_a_bad_lookup_change_is_a_422(search_client):
    r = search_client.post(
        "/v1/search",
        json={
            "prompt": "x",
            "query": Query(intent="lookup").model_dump(mode="json"),
            "change": {"slot": "nope", "value": 1},
        },
    )
    assert r.status_code == 422


def test_a_card_number_in_a_prompt_is_masked_before_the_models(search_client, spy_reader):
    from household_vault.checks import TEST_CARD_NUMBERS

    number = sorted(TEST_CARD_NUMBERS)[0]
    spaced = " ".join(number[i : i + 4] for i in range(0, len(number), 4))
    post(search_client, f"my card {spaced} bill")
    seen = " ".join(str(p) for p in spy_reader.prompts)
    assert number not in seen and spaced not in seen and number[-4:] in seen


def test_item_lengths_are_bounded(search_client):
    q = Query(intent="list").model_dump(mode="json")
    for patch in ({"people": ["x" * 65]}, {"unread": ["x" * 301]}):
        r = search_client.post("/v1/search/list", json={"query": {**q, **patch}})
        assert r.status_code == 422
    r = search_client.post(
        "/v1/search/list",
        json={"query": q, "change": {"slot": "place", "value": "x" * 301}},
    )
    assert r.status_code == 422


def _with_check_digit(body: str) -> str:
    from household_vault.checks import luhn_valid

    return next(body + str(d) for d in range(10) if luhn_valid(body + str(d)))


def _prompts_seen(client, spy_reader, text: str) -> str:
    post(client, text)
    return " ".join(str(p) for p in spy_reader.prompts)


def test_an_imei_stays_whole_in_a_prompt(search_client, spy_reader):
    imei = "490154203237518"  # the published example IMEI: 15 digits, Luhn-valid, not a card
    assert imei in _prompts_seen(search_client, spy_reader, f"invoice IMEI {imei}")


def test_a_long_policy_number_is_not_masked(search_client, spy_reader):
    policy = _with_check_digit("9" + "2468013579" * 1 + "135")  # Luhn-valid, no card brand
    assert policy in _prompts_seen(search_client, spy_reader, f"policy {policy}")


def test_dotted_and_slashed_card_numbers_are_masked(search_client, spy_reader):
    from household_vault.checks import TEST_CARD_NUMBERS

    number = "4111111111111111"
    assert number in TEST_CARD_NUMBERS
    for sep in (".", "/"):
        text = sep.join(number[i : i + 4] for i in range(0, 16, 4))
        spy_reader.prompts.clear()
        seen = _prompts_seen(search_client, spy_reader, f"card {text} bill")
        assert text not in seen and number[:12] not in seen and number[-4:] in seen


def test_each_brand_range_is_masked(search_client, spy_reader):
    from household_vault.checks import TEST_CARD_NUMBERS

    for number in sorted(TEST_CARD_NUMBERS):
        spy_reader.prompts.clear()
        seen = _prompts_seen(search_client, spy_reader, f"card {number}")
        assert number not in seen and number[-4:] in seen


def test_a_who_change_on_a_held_unknown_person_lists_again(search_client):
    held = Query(intent="list", types=[DocType.health_policy], unread=["person: Meera"])
    r = search_client.post(
        "/v1/search/list",
        json={
            "query": held.model_dump(mode="json"),
            "change": {"slot": "who", "value": "p4"},
        },
    )
    assert r.status_code == 200
    assert r.json()["query"]["unread"] == []
    assert r.json()["rows"]


def test_a_crafted_before_date_is_a_422(search_client):
    r = search_client.post(
        "/v1/search/list",
        json={"query": a_list_query(), "change": {"slot": "when", "value": "before:0001-01-01"}},
    )
    assert r.status_code == 422
