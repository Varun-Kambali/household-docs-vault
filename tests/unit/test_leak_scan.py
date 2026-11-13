"""CI scan of committed outputs: no real-shaped Aadhaar or card number may be published.

Results files hold raw model output, and a model that misreads one digit of a synthetic Aadhaar
has about a 1 in 9 chance of landing on a number that passes the public Verhoeff check.
"""

import re
import subprocess
from pathlib import Path

from vault_synth.checks import TEST_CARD_NUMBERS, luhn_valid, verhoeff_valid

ROOT = Path(__file__).resolve().parents[2]
SUFFIXES = {".json", ".md", ".yaml", ".yml", ".txt"}
SKIP_DIRS = {".venv", ".worktrees", ".git", "node_modules"}

_TOKEN = re.compile(r"\d+")


def _mask(digits: str) -> str:
    # CI logs on this repo are public: show the last four digits only
    return "*" * (len(digits) - 4) + digits[-4:] if len(digits) > 4 else "*" * len(digits)


def _runs(text: str) -> list[list[tuple[str, str]]]:
    """Split text into runs of digit groups joined by one space or dash.

    Each run is a list of (digits, separator before it). A group that is part of a float
    ("1.123" or "123.5") is dropped and ends the run.
    """
    runs: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
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
        current.append((m.group(), sep if joined else ""))
        prev_end = m.end()
    if current:
        runs.append(current)
    return runs


def scan_text(text: str) -> list[str]:
    """Return masked descriptions of every Aadhaar-shaped or card-shaped number in text.

    Every window of consecutive groups in a separator-joined run is tested, so a number that
    follows or precedes other digits ("DOB 1990 2345 6789 0124", a card then " 12") is found.
    """
    found: list[str] = []
    seen: set[str] = set()
    for run in _runs(text):
        digits = [d for d, _ in run]
        test_card_spans: list[tuple[int, int]] = []
        for i in range(len(run)):
            for j in range(i, len(run)):
                number = "".join(digits[i : j + 1])
                if len(number) > 19:
                    break
                if 13 <= len(number) <= 19:
                    if number in TEST_CARD_NUMBERS:
                        test_card_spans.append((i, j))
                    elif luhn_valid(number) and number not in seen:
                        seen.add(number)
                        found.append(f"card-shaped {_mask(number)}")
        # 12 digits as one group, or three groups of four joined by spaces
        for i in range(len(run)):
            windows = []
            if len(digits[i]) == 12:
                windows.append((i, i))
            if (
                i + 2 < len(run)
                and all(len(digits[k]) == 4 for k in range(i, i + 3))
                and run[i + 1][1] == " "
                and run[i + 2][1] == " "
            ):
                windows.append((i, i + 2))
            for lo, hi in windows:
                if any(s <= lo and hi <= e for s, e in test_card_spans):
                    continue
                number = "".join(digits[lo : hi + 1])
                key = "A" + number
                if verhoeff_valid(number) and key not in seen:
                    seen.add(key)
                    found.append(f"Aadhaar-shaped {_mask(number)}")
    return found


def committed_outputs(root: Path = ROOT) -> list[Path]:
    """Tracked text files under any results folder or under evals/. Symlinks are never followed."""
    try:
        listing = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split("\0")
        candidates = [root / name for name in listing if name]
    except (subprocess.CalledProcessError, FileNotFoundError):
        candidates = [p for p in root.rglob("*") if not SKIP_DIRS & set(p.relative_to(root).parts)]
    files = []
    for p in candidates:
        rel = p.relative_to(root).parts
        wanted = rel[0] == "evals" or "results" in rel[:-1]
        if wanted and p.suffix in SUFFIXES and p.is_file() and not p.is_symlink():
            files.append(p)
    return sorted(files)


def _valid_aadhaar_like() -> str:
    body = "23456789012"
    return body + next(d for d in "0123456789" if verhoeff_valid(body + d))


def _valid_card_like() -> str:
    body = "453201511283036"
    return body + next(d for d in "0123456789" if luhn_valid(body + d))


def test_scanner_flags_a_verhoeff_valid_twelve_digit_run() -> None:
    number = _valid_aadhaar_like()
    spaced = f"{number[:4]} {number[4:8]} {number[8:]}"
    expected = [f"Aadhaar-shaped {'*' * 8}{number[-4:]}"]
    assert scan_text(f"read: {number} here") == expected
    assert scan_text(f"read: {spaced}.") == expected


def test_scanner_ignores_longer_runs_and_floats() -> None:
    number = _valid_aadhaar_like()
    assert scan_text(f"7{number}") == []
    assert scan_text(f"{number}8") == []
    assert scan_text(f"1.{number}") == []
    assert scan_text(f"{number}.5") == []


def test_scanner_finds_a_spaced_aadhaar_after_another_group() -> None:
    number = _valid_aadhaar_like()
    spaced = f"{number[:4]} {number[4:8]} {number[8:]}"
    assert len(scan_text(f"DOB 1990 {spaced}")) == 1
    assert len(scan_text(f"{spaced} 2026")) == 1


def test_scanner_flags_a_luhn_valid_card_but_not_published_test_cards() -> None:
    number = _valid_card_like()
    assert len(number) == 16
    expected = [f"card-shaped {'*' * 12}{number[-4:]}"]
    assert scan_text(f"card {number}") == expected
    dashed = "-".join(number[i : i + 4] for i in range(0, 16, 4))
    assert scan_text(dashed) == expected
    assert scan_text("4111 1111 1111 1111 and 5555555555554444 and 378282246310005") == []


def test_scanner_finds_a_card_followed_by_other_digits() -> None:
    number = _valid_card_like()
    spaced = " ".join(number[i : i + 4] for i in range(0, 16, 4))
    for tail in (" 7 items", " 12"):
        hits = scan_text(spaced + tail)
        assert f"card-shaped {'*' * 12}{number[-4:]}" in hits
    assert scan_text("4111 1111 1111 1111 7 items") == []


def test_scan_output_shows_only_the_last_four_digits() -> None:
    number = _valid_card_like()
    (hit,) = scan_text(number)
    assert number[:-4] not in hit and hit.endswith(number[-4:])


def test_listing_skips_symlinks_and_other_folders(tmp_path: Path) -> None:
    (tmp_path / "evals").mkdir()
    (tmp_path / "evals" / "real.txt").write_text("ok")
    (tmp_path / "evals" / "image.png").write_text("not text")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.txt").write_text("outside the scan")
    (tmp_path / "spikes" / "results").mkdir(parents=True)
    (tmp_path / "spikes" / "results" / "r.json").write_text("{}")
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("secret")
    (tmp_path / "evals" / "link.txt").symlink_to(outside)
    names = [p.relative_to(tmp_path).as_posix() for p in committed_outputs(tmp_path)]
    assert names == ["evals/real.txt", "spikes/results/r.json"]


def test_committed_outputs_hold_no_real_shaped_numbers() -> None:
    files = committed_outputs()
    assert files, "the scan found no files, so its listing is wrong"
    hits = [
        f"{p.relative_to(ROOT)}: {hit}"
        for p in files
        for hit in scan_text(p.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert not hits, "\n".join(hits)
