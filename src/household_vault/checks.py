"""Checksums and the one finder for card and Aadhaar numbers in text.

Synthetic IDs are provably not real (they fail these checks) and test cards are published ones.
Real numbers always pass, so in app mode a failure on a real document means a misread digit.
"""

import re
from dataclasses import dataclass
from typing import Literal

_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


def verhoeff_valid(digits: str) -> bool:
    if not digits.isdigit():
        return False
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def luhn_valid(digits: str) -> bool:
    if not digits.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


# Published test numbers from the networks and payment providers; none belongs to a person.
TEST_CARD_NUMBERS: frozenset[str] = frozenset(
    {
        "4111111111111111",  # Visa
        "4012888888881881",  # Visa
        "5555555555554444",  # Mastercard
        "5105105105105100",  # Mastercard
        "378282246310005",  # Amex
        "6011111111111117",  # Discover
        "3056930009020004",  # Diners
    }
)


_GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_check_char(first14: str) -> str:
    """The published GSTIN check character: mod-36 sum with weights 1, 2, 1, 2 and so on."""
    total = 0
    for i, ch in enumerate(first14):
        product = _GSTIN_CHARS.index(ch) * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return _GSTIN_CHARS[(36 - total % 36) % 36]


def gstin_valid(gstin: str) -> bool:
    return (
        len(gstin) == 15
        and all(c in _GSTIN_CHARS for c in gstin)
        and gstin[14] == gstin_check_char(gstin[:14])
    )


def id_checksum_issue(
    kind: Literal["aadhaar", "gstin"], value: str, *, mode: Literal["dev", "app"]
) -> str | None:
    """The issue for an ID that fails its checksum, or None.

    Only app mode checks: the synthetic numbers in development fail on purpose.
    """
    if mode != "app":
        return None
    squeezed = re.sub(r"[\s-]", "", value)
    ok = (
        len(squeezed) == 12 and verhoeff_valid(squeezed)
        if kind == "aadhaar"
        else gstin_valid(squeezed.upper())
    )
    return None if ok else "number may be misread"


@dataclass(frozen=True)
class NumberHit:
    start: int
    end: int
    digits: str
    kind: Literal["card", "aadhaar"]


_TOKEN = re.compile(r"\d+")


@dataclass(frozen=True)
class _Group:
    start: int
    end: int
    digits: str
    sep: str  # the separator before it when it joins the group before, else ""


def _runs(text: str) -> list[list[_Group]]:
    """Runs of digit groups joined by one space or hyphen.

    A group that is part of a decimal number is dropped and ends the run.
    """
    runs: list[list[_Group]] = []
    current: list[_Group] = []
    prev_end = -1
    for m in _TOKEN.finditer(text):
        before, after = text[max(0, m.start() - 2) : m.start()], text[m.end() : m.end() + 2]
        is_float = bool(re.fullmatch(r"\d\.", before)) or bool(re.fullmatch(r"\.\d", after))
        sep = text[prev_end : m.start()] if prev_end >= 0 else ""
        joined = bool(current) and m.start() - prev_end == 1 and sep in (" ", "-")
        if is_float:
            if current:
                runs.append(current)
            current, prev_end = [], -1
            continue
        if not joined and current:
            runs.append(current)
            current = []
        current.append(_Group(m.start(), m.end(), m.group(), sep if joined else ""))
        prev_end = m.end()
    if current:
        runs.append(current)
    return runs


def find_numbers(
    text: str, *, allow_test_cards: bool, any_long_run: bool = False
) -> list[NumberHit]:
    """Every card-shaped and Aadhaar-shaped number in text, in order of position.

    Every window of consecutive groups in a run is tried, so a number that follows or precedes
    other digits is found. A card is 13 to 19 digits passing Luhn (the published test numbers
    only when allow_test_cards is False). With any_long_run every 13 to 19 digit window counts.
    An Aadhaar number is 12 digits, as one group or three groups of four joined by spaces,
    passing Verhoeff, and not inside a card hit.
    """
    hits: list[NumberHit] = []
    for run in _runs(text):
        card_spans: list[tuple[int, int]] = []  # group index ranges, test cards included
        for i in range(len(run)):
            digits = ""
            for j in range(i, len(run)):
                digits += run[j].digits
                if len(digits) > 19:
                    break
                if len(digits) < 13:
                    continue
                is_test = digits in TEST_CARD_NUMBERS
                if any_long_run:
                    counts = not (is_test and allow_test_cards)
                    shaped = True
                else:
                    shaped = luhn_valid(digits)
                    counts = shaped and not (is_test and allow_test_cards)
                if shaped:
                    card_spans.append((i, j))
                if counts:
                    hits.append(NumberHit(run[i].start, run[j].end, digits, "card"))
        for i in range(len(run)):
            windows = []
            if len(run[i].digits) == 12:
                windows.append((i, i))
            if (
                i + 2 < len(run)
                and all(len(run[k].digits) == 4 for k in range(i, i + 3))
                and run[i + 1].sep == " "
                and run[i + 2].sep == " "
            ):
                windows.append((i, i + 2))
            for lo, hi in windows:
                if any(s <= lo and hi <= e for s, e in card_spans):
                    continue
                digits = "".join(g.digits for g in run[lo : hi + 1])
                if verhoeff_valid(digits):
                    hits.append(NumberHit(run[lo].start, run[hi].end, digits, "aadhaar"))
    return sorted(hits, key=lambda h: (h.start, h.end))
