import random

from vault_synth.checks import gstin_check_char, gstin_valid
from vault_synth.templates.tax_invoice import STATE_CODES, _gstin

_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _independent_check(first14: str) -> str:
    # same published rule written the long way: value * (1 or 2), split in base 36, sum
    total = 0
    for i, c in enumerate(first14):
        v = _CHARS.index(c) * (2 if i % 2 else 1)
        total += (v // 36) + (v % 36)
    return _CHARS[(36 - (total % 36)) % 36]


def test_check_character_matches_the_published_rule_on_a_constructed_sample() -> None:
    body = "29ABCDE1234F1Z"  # made up for this test, not a registered business
    check = _independent_check(body)
    assert gstin_check_char(body) == check
    assert gstin_valid(body + check)


def test_a_wrong_check_character_is_invalid() -> None:
    body = "29ABCDE1234F1Z"
    good = gstin_check_char(body)
    bad = next(c for c in _CHARS if c != good)
    assert not gstin_valid(body + bad)
    assert not gstin_valid(body)  # wrong length


def test_generated_gstins_fail_the_checksum() -> None:
    for seed in range(300):
        for state in STATE_CODES:
            assert not gstin_valid(_gstin(random.Random(seed), state)), (seed, state)
