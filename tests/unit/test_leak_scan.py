"""CI scan of committed outputs: no real-shaped Aadhaar or card number may be published.

Results files hold raw model output, and a model that misreads one digit of a synthetic Aadhaar
has about a 1 in 10 chance of landing on a number that passes the public Verhoeff check.
"""

import re
from pathlib import Path

from vault_synth.checks import TEST_CARD_NUMBERS, luhn_valid, verhoeff_valid

ROOT = Path(__file__).resolve().parents[2]
SUFFIXES = {".json", ".md", ".yaml", ".yml", ".txt"}

# Not part of a longer digit run or a float: no digit before, no digit or ".digit" after.
_BEFORE = r"(?<!\d)(?<!\d\.)"
_AFTER = r"(?!\d)(?!\.\d)"
AADHAAR = re.compile(_BEFORE + r"(\d{4} \d{4} \d{4}|\d{12})" + _AFTER)
CARD = re.compile(_BEFORE + r"(\d(?:[ -]?\d){12,18})" + _AFTER)


def _mask(text: str) -> str:
    return text[:2] + "*" * (len(text) - 6) + text[-4:] if len(text) > 6 else "*" * len(text)


def scan_text(text: str) -> list[str]:
    """Return masked descriptions of every Aadhaar-shaped or card-shaped number in text."""
    found: list[str] = []
    card_spans: list[tuple[int, int]] = []
    for m in CARD.finditer(text):
        digits = re.sub(r"\D", "", m.group(1))
        if not 13 <= len(digits) <= 19:
            continue
        if digits in TEST_CARD_NUMBERS:
            card_spans.append(m.span())  # a published test card, also hides its 12-digit prefix
        elif luhn_valid(digits):
            found.append(f"card-shaped {_mask(digits)}")
    for m in AADHAAR.finditer(text):
        if any(s <= m.start() < e or s < m.end() <= e for s, e in card_spans):
            continue
        digits = m.group(1).replace(" ", "")
        if verhoeff_valid(digits):
            found.append(f"Aadhaar-shaped {_mask(digits)}")
    return found


def committed_outputs() -> list[Path]:
    files = [
        p
        for pattern in ("**/results/**/*", "evals/**/*")
        for p in ROOT.glob(pattern)
        if p.is_file()
        and p.suffix in SUFFIXES
        and not {".venv", ".worktrees", ".git", "node_modules"} & set(p.relative_to(ROOT).parts)
    ]
    return sorted(set(files))


def test_scanner_flags_a_verhoeff_valid_twelve_digit_run() -> None:
    # build a number whose last digit makes the Verhoeff total zero
    body = "23456789012"
    check = next(d for d in "0123456789" if verhoeff_valid(body + d))
    number = body + check
    spaced = f"{number[:4]} {number[4:8]} {number[8:]}"
    assert scan_text(f"read: {number} here") == [f"Aadhaar-shaped {_mask(number)}"]
    assert scan_text(f"read: {spaced}.") == [f"Aadhaar-shaped {_mask(number)}"]


def test_scanner_ignores_longer_runs_and_floats() -> None:
    body = "23456789012"
    number = body + next(d for d in "0123456789" if verhoeff_valid(body + d))
    assert scan_text(f"7{number}") == []
    assert scan_text(f"{number}8") == []
    assert scan_text(f"1.{number}") == []
    assert scan_text(f"{number}.5") == []


def test_scanner_flags_a_luhn_valid_card_but_not_published_test_cards() -> None:
    body = "453201511283036"
    number = body + next(d for d in "0123456789" if luhn_valid(body + d))
    assert scan_text(f"card {number}") == [f"card-shaped {_mask(number)}"]
    dashed = "-".join(number[i : i + 4] for i in range(0, 16, 4))
    assert scan_text(dashed) == [f"card-shaped {_mask(number)}"]
    assert scan_text("4111 1111 1111 1111 and 5555555555554444 and 378282246310005") == []


def test_committed_outputs_hold_no_real_shaped_numbers() -> None:
    files = committed_outputs()
    assert files, "the scan found no files, so its globs are wrong"
    hits = [
        f"{p.relative_to(ROOT)}: {hit}"
        for p in files
        for hit in scan_text(p.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert not hits, "\n".join(hits)
