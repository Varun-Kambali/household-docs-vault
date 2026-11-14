import random
import string

from vault_synth import checks as synth_checks

from household_vault import checks
from household_vault.checks import (
    TEST_CARD_NUMBERS,
    find_numbers,
    gstin_check_char,
    id_checksum_issue,
    luhn_valid,
    verhoeff_valid,
)
from tests.conftest import one_digit_changed, valid_aadhaar, valid_gstin


def _card_like(rng: random.Random) -> str:
    body = "4" + "".join(rng.choice(string.digits) for _ in range(14))
    return body + next(d for d in string.digits if luhn_valid(body + d))


def test_synth_checks_are_the_same_functions() -> None:
    assert synth_checks.luhn_valid is checks.luhn_valid
    assert synth_checks.verhoeff_valid is checks.verhoeff_valid
    assert synth_checks.gstin_check_char is checks.gstin_check_char
    assert synth_checks.TEST_CARD_NUMBERS is checks.TEST_CARD_NUMBERS


def test_published_test_cards_pass_luhn() -> None:
    assert all(luhn_valid(n) for n in TEST_CARD_NUMBERS)
    assert not luhn_valid("4111111111111112")


def test_runtime_built_ids_pass_their_checks() -> None:
    assert verhoeff_valid(valid_aadhaar())
    gstin = valid_gstin()
    assert gstin[14] == gstin_check_char(gstin[:14])


def test_one_finder_for_cards_and_aadhaar_numbers() -> None:
    aadhaar = valid_aadhaar()
    hits = find_numbers(
        f"x 4111 1111 1111 1111 y {aadhaar[:4]} {aadhaar[4:8]} {aadhaar[8:]} 1.5",
        allow_test_cards=False,
    )
    assert [h.kind for h in hits] == ["card", "aadhaar"]
    assert find_numbers("4111 1111 1111 1111", allow_test_cards=True) == []


def test_hit_positions_and_digits() -> None:
    aadhaar = valid_aadhaar()
    text = f"id {aadhaar} end"
    (hit,) = find_numbers(text, allow_test_cards=True)
    assert (hit.start, hit.end, hit.digits) == (3, 15, aadhaar)
    assert text[hit.start : hit.end] == aadhaar


def test_finder_ignores_longer_runs_and_floats() -> None:
    aadhaar = valid_aadhaar()
    # a 13-digit run could pass Luhn by chance, so pick the extra digit that does not
    before = next(d for d in "1234567" if not luhn_valid(d + aadhaar))
    after = next(d for d in "1234567" if not luhn_valid(aadhaar + d))
    for text in (f"{before}{aadhaar}", f"{aadhaar}{after}", f"1.{aadhaar}", f"{aadhaar}.5"):
        assert find_numbers(text, allow_test_cards=False) == []


def test_finder_finds_a_number_next_to_other_groups() -> None:
    aadhaar = valid_aadhaar()
    spaced = f"{aadhaar[:4]} {aadhaar[4:8]} {aadhaar[8:]}"
    # 16 digits could pass Luhn by chance and then count as a card, so pick a year that does not
    year = next(y for y in range(1990, 2000) if not luhn_valid(f"{y}{aadhaar}"))
    hits = find_numbers(f"DOB {year} {spaced}", allow_test_cards=False)
    assert aadhaar in [h.digits for h in hits]
    card = _card_like(random.Random(3))
    dashed = "-".join(card[i : i + 4] for i in range(0, 16, 4))
    hits = find_numbers(dashed + " 12", allow_test_cards=False)
    assert card in [h.digits for h in hits]


def test_any_long_run_counts_a_card_that_fails_luhn() -> None:
    assert find_numbers("4111 1111 1111 1112", allow_test_cards=False) == []
    (hit,) = find_numbers("4111 1111 1111 1112", allow_test_cards=False, any_long_run=True)
    assert hit.kind == "card" and hit.digits == "4111111111111112"


def test_aadhaar_inside_a_card_is_not_reported_twice() -> None:
    card = _card_like(random.Random(0))
    assert verhoeff_valid(card[:12])  # a window that would be an Aadhaar number on its own
    spaced = " ".join(card[i : i + 4] for i in range(0, 16, 4))
    kinds = {h.kind for h in find_numbers(spaced, allow_test_cards=False)}
    assert kinds == {"card"}


def test_app_mode_flags_a_misread_id_and_dev_mode_does_not() -> None:
    aadhaar, gstin = valid_aadhaar(), valid_gstin()
    assert id_checksum_issue("aadhaar", aadhaar, mode="app") is None
    assert (
        id_checksum_issue("aadhaar", f"{aadhaar[:4]} {aadhaar[4:8]} {aadhaar[8:]}", mode="app")
        is None
    )
    assert id_checksum_issue("gstin", gstin, mode="app") is None
    assert id_checksum_issue("aadhaar", one_digit_changed(aadhaar), mode="app") == (
        "number may be misread"
    )
    assert id_checksum_issue("gstin", one_digit_changed(gstin), mode="app") == (
        "number may be misread"
    )
    for kind, value in (
        ("aadhaar", one_digit_changed(aadhaar)),
        ("gstin", one_digit_changed(gstin)),
    ):
        assert id_checksum_issue(kind, value, mode="dev") is None  # type: ignore[arg-type]
