"""CI scan of committed outputs: no real-shaped Aadhaar or card number may be published.

Results files hold raw model output, and a model that misreads one digit of a synthetic Aadhaar
has about a 1 in 9 chance of landing on a number that passes the public Verhoeff check.
"""

import subprocess
from pathlib import Path

from household_vault.checks import luhn_valid, verhoeff_valid
from household_vault.leakscan import scan_text as scan_text_in_src

ROOT = Path(__file__).resolve().parents[2]
SUFFIXES = {".json", ".md", ".yaml", ".yml", ".txt"}
SKIP_DIRS = {".venv", ".worktrees", ".git", "node_modules"}


def scan_text(text: str) -> list[str]:
    """The scan of committed outputs: published test cards are allowed there."""
    return scan_text_in_src(text, allow_test_cards=True)


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
    expected = [f"Aadhaar-shaped {'X' * 8}{number[-4:]}"]
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
    expected = [f"card-shaped {'X' * 12}{number[-4:]}"]
    assert scan_text(f"card {number}") == expected
    dashed = "-".join(number[i : i + 4] for i in range(0, 16, 4))
    assert scan_text(dashed) == expected
    assert scan_text("4111 1111 1111 1111 and 5555555555554444 and 378282246310005") == []


def test_scanner_finds_a_card_followed_by_other_digits() -> None:
    number = _valid_card_like()
    spaced = " ".join(number[i : i + 4] for i in range(0, 16, 4))
    for tail in (" 7 items", " 12"):
        hits = scan_text(spaced + tail)
        assert f"card-shaped {'X' * 12}{number[-4:]}" in hits
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
