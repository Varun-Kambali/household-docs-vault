"""Score a transcript against the visit script.

Text is normalised the same way on both sides: lower case, punctuation removed, whitespace
collapsed. Number words are not converted to digits or back; a model that writes "forty" where
the script has "40" pays for it in WER, and `style_counts` reports how often each style appears.
The medicine check uses its own normalisation (`normalise_for_medicines`) that keeps decimals whole.
"""

import re
from dataclasses import dataclass

import jiwer

_NUMBER_WORDS = frozenset(
    [
        "zero",
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "eleven",
        "twelve",
        "thirteen",
        "fourteen",
        "fifteen",
        "sixteen",
        "seventeen",
        "eighteen",
        "nineteen",
        "twenty",
        "thirty",
        "forty",
        "fifty",
        "sixty",
        "seventy",
        "eighty",
        "ninety",
        "hundred",
        "thousand",
    ]
)


@dataclass(frozen=True)
class VisitScore:
    wer: float
    medicines_found: int
    medicines_total: int
    # Medicines whose name appears, with or without the dose; a dose written as a word still counts.
    names_found: int = 0


def normalise(text: str) -> str:
    text = re.sub(r"['\u2019]", "", text.lower())
    text = re.sub(r"[^\w\s]|_", " ", text)
    return " ".join(text.split())


def normalise_for_medicines(text: str) -> str:
    """Like `normalise`, but a point between two digits is kept, so 40.5 is not read as 40 5.

    Also writes "500mg" as "500 mg", so an attached unit is not a miss. Used only for the
    medicine check; WER uses `normalise`.
    """
    text = re.sub(r"['\u2019]", "", text.lower())
    text = re.sub(r"(?<!\d)\.|\.(?!\d)|[^\w\s.]|_", " ", text)
    text = re.sub(r"(?<=\d)(?=[a-z])", " ", text)
    return " ".join(text.split())


def _contains(haystack: str, needle: str) -> bool:
    """Whole-token match: "telma 40" does not match inside "telma 400" or "telma 40.5"."""
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w|\.\d)", haystack) is not None


def _without_dose(name: str) -> str:
    return re.sub(r"(\s\d+(\.\d+)?)+$", "", name)


def score_visit(truth_text: str, got_text: str, medicines: list[str]) -> VisitScore:
    truth, got = normalise(truth_text), normalise(got_text)
    wer = float(jiwer.wer(truth, got)) if truth else (0.0 if not got else 1.0)
    heard = normalise_for_medicines(got_text)
    found = sum(_contains(heard, normalise_for_medicines(m)) for m in medicines)
    names = sum(_contains(heard, _without_dose(normalise_for_medicines(m))) for m in medicines)
    return VisitScore(wer, found, len(medicines), names)


def style_counts(text: str) -> dict[str, int]:
    tokens = normalise(text).split()
    return {
        "digit_tokens": sum(t.isdigit() for t in tokens),
        "number_words": sum(t in _NUMBER_WORDS for t in tokens),
        "mg_tokens": sum(t == "mg" for t in tokens),
    }
