"""GET and PUT /v1/documents/{id}/notes: where the paper original is and a login hint."""

import logging

import pytest

from household_vault.checks import TEST_CARD_NUMBERS

CARD_MESSAGE = "Card numbers go in Secrets.kdbx."


def url(doc_id: str) -> str:
    return f"/v1/documents/{doc_id}/notes"


def test_notes_start_empty_and_round_trip(search_client, filed_ids):
    d = filed_ids[0]
    assert search_client.get(url(d)).json() == {"paper": "", "login": ""}
    body = {"paper": "Steel cupboard", "login": "Use the mobile number"}
    r = search_client.put(url(d), json=body)
    assert r.status_code == 200
    assert r.json() == body
    assert search_client.get(url(d)).json() == r.json()
    assert search_client.get(url(filed_ids[1])).json() == {"paper": "", "login": ""}


def test_notes_for_an_unknown_document_are_404(search_client):
    assert search_client.get(url("nope")).status_code == 404
    assert search_client.put(url("nope"), json={"paper": "a", "login": "b"}).status_code == 404


def test_notes_over_200_characters_are_refused(search_client, filed_ids, search_state):
    d = filed_ids[0]
    ok = "x" * 200
    assert search_client.put(url(d), json={"paper": ok, "login": ok}).status_code == 200
    for body in ({"paper": "y" * 201, "login": ""}, {"paper": "", "login": "y" * 201}):
        r = search_client.put(url(d), json=body)
        assert r.status_code == 422
    assert search_client.get(url(d)).json() == {"paper": ok, "login": ok}  # nothing stored


def test_notes_refuse_a_card_number(search_client, filed_ids):
    d = filed_ids[0]
    number = sorted(TEST_CARD_NUMBERS)[0]
    spaced = " ".join(number[i : i + 4] for i in range(0, len(number), 4))
    for text in (number, spaced, f"in the drawer, card {spaced} too"):
        for field in ("paper", "login"):
            body = {"paper": "", "login": "", field: text}
            r = search_client.put(url(d), json=body)
            assert r.status_code == 422 and r.json()["detail"] == CARD_MESSAGE
    assert search_client.get(url(d)).json() == {"paper": "", "login": ""}


def test_notes_may_hold_other_long_numbers(search_client, filed_ids):
    imei = "490154203237518"
    r = search_client.put(url(filed_ids[0]), json={"paper": f"IMEI {imei}", "login": ""})
    assert r.status_code == 200 and imei in r.json()["paper"]


def test_notes_are_plain_text_without_control_characters(search_client, filed_ids):
    r = search_client.put(url(filed_ids[0]), json={"paper": "a\x00b\x1bc‮d\n\te", "login": "  hi  "})
    assert r.status_code == 200
    assert r.json() == {"paper": "abc‮d e", "login": "hi"} or r.json()["login"] == "hi"
    assert not any(ord(c) < 32 for c in r.json()["paper"])


def test_notes_refuse_unknown_fields_and_a_non_string(search_client, filed_ids):
    d = filed_ids[0]
    assert search_client.put(url(d), json={"paper": "a", "login": "b", "x": 1}).status_code == 422
    assert search_client.put(url(d), json={"paper": 5, "login": "b"}).status_code == 422
    assert search_client.put(url(d), json={"paper": "a"}).status_code == 422


def test_a_page_on_another_site_cannot_put_notes(search_client, filed_ids):
    r = search_client.put(
        url(filed_ids[0]),
        json={"paper": "a", "login": "b"},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403
    assert search_client.get(url(filed_ids[0])).json()["paper"] == ""


def test_notes_body_limit_is_enforced(search_client, filed_ids):
    r = search_client.put(url(filed_ids[0]), content=b"{" + b" " * 3_000_000 + b"}")
    assert r.status_code in (413, 422)


def test_note_text_is_never_logged(search_client, filed_ids, caplog):
    caplog.set_level(logging.DEBUG)
    search_client.put(url(filed_ids[0]), json={"paper": "secretive cupboard", "login": "hint-xyz"})
    search_client.put(url(filed_ids[0]), json={"paper": "4111 1111 1111 1111", "login": ""})
    assert "secretive" not in caplog.text and "hint-xyz" not in caplog.text
    assert "4111" not in caplog.text


@pytest.mark.parametrize("doc", [0, 1, 2])
def test_removing_a_document_drops_its_notes(search_client, search_state, filed_ids, doc):
    d = filed_ids[doc]
    search_client.put(url(d), json={"paper": "here", "login": ""})
    search_state.store.remove_document(d)
    assert (
        search_state.store.conn.execute(
            "select count(*) from notes where document_id = ?", (d,)
        ).fetchone()[0]
        == 0
    )
