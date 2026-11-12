from vault_synth.model import LineBox

from spikes.reading.engines import OcrLine
from spikes.reading.score import cer, score_page

BOX = (0.10, 0.10, 0.50, 0.15)


def _line(text: str, bbox: tuple[float, float, float, float] = BOX, lang: str = "en") -> LineBox:
    return LineBox(text=text, page=0, bbox=bbox, lang=lang)  # type: ignore[arg-type]


def _ocr(line: LineBox) -> OcrLine:
    return OcrLine(line.text, line.bbox, None)


TRUTH = [
    _line("Government of India"),
    _line("Policy No: 12345", (0.10, 0.20, 0.50, 0.25)),
]


def test_perfect_read_scores_one():
    s = score_page(TRUTH, [_ocr(line) for line in TRUTH])
    assert s.cer == 0
    assert s.line_recall == 1
    assert s.matched == 2


def test_line_counts_only_with_overlap_and_text():
    # same text, box moved off by half its width -> IoU < 0.5 -> not matched
    shifted = (0.30, 0.10, 0.70, 0.15)
    s = score_page(TRUTH[:1], [OcrLine(TRUTH[0].text, shifted, None)])
    assert s.matched == 0


def test_line_not_matched_when_text_is_wrong():
    s = score_page(TRUTH[:1], [OcrLine("Xxxxxxxxxxx xx xxxxx", BOX, None)])
    assert s.matched == 0


def test_small_misread_still_matches():
    s = score_page(TRUTH[:1], [OcrLine("Government of lndia", BOX, None)])
    assert s.matched == 1
    assert 0 < s.cer < 0.2


def test_scoring_skips_non_english_lines():
    kn = _line("ಭಾರತ ಸರ್ಕಾರ", (0.1, 0.5, 0.5, 0.55), lang="kn")
    mixed = [kn, TRUTH[0]]
    assert score_page(mixed, [_ocr(TRUTH[0])]).truth_lines == 1


def test_missing_line_counts_against_recall_and_cer():
    s = score_page(TRUTH, [_ocr(TRUTH[0])])
    assert s.line_recall == 0.5
    assert s.cer > 0


def test_cer_is_edit_distance_over_length():
    assert cer("abcd", "abxd") == 0.25
    assert cer("abcd", "") == 1.0
