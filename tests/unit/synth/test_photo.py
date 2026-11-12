import random

import numpy as np
from PIL import Image, ImageDraw
from vault_synth.model import LineBox
from vault_synth.photo import to_photo


def _clean() -> tuple[Image.Image, list[LineBox]]:
    img = Image.new("RGB", (800, 1000), "white")
    d = ImageDraw.Draw(img)
    d.rectangle((80, 100, 700, 140), fill="black")
    lines = [
        LineBox(text="Top line", page=0, bbox=(0.1, 0.1, 0.875, 0.14), lang="en"),
        LineBox(text="Edge line", page=0, bbox=(0.0, 0.9, 1.0, 1.0), lang="en"),
    ]
    return img, lines


def test_photo_boxes_stay_inside_and_follow_text() -> None:
    clean_image, clean_lines = _clean()
    img, lines = to_photo(clean_image, clean_lines, random.Random(1))
    assert all(0 <= v <= 1 for line in lines for v in line.bbox)
    assert len(lines) == len(clean_lines)
    assert [line.text for line in lines] == [line.text for line in clean_lines]
    assert img.size == clean_image.size


def test_photo_moves_boxes_with_the_warp() -> None:
    clean_image, clean_lines = _clean()
    _, lines = to_photo(clean_image, clean_lines, random.Random(1))
    assert lines[0].bbox != clean_lines[0].bbox
    # still near where it was: the warp moves corners by at most 6% of the width
    assert all(abs(a - b) < 0.2 for a, b in zip(lines[0].bbox, clean_lines[0].bbox, strict=True))


def test_photo_boxes_match_the_warped_pixels() -> None:
    """Measure where the dark bar really ended up and compare it with the mapped box."""
    clean_image, clean_lines = _clean()
    img, lines = to_photo(clean_image, clean_lines[:1], random.Random(3))
    # the desk is mid-grey and the shadow keeps white well above 40, so only the bar is darker
    dark = np.asarray(img.convert("L")) < 40
    ys, xs = np.nonzero(dark)
    w, h = img.size
    measured = (xs.min() / w, ys.min() / h, (xs.max() + 1) / w, (ys.max() + 1) / h)
    assert all(abs(m - b) < 0.012 for m, b in zip(measured, lines[0].bbox, strict=True))


def test_photo_is_deterministic_for_a_seed() -> None:
    clean_image, clean_lines = _clean()
    _, a = to_photo(clean_image, clean_lines, random.Random(5))
    _, b = to_photo(clean_image, clean_lines, random.Random(5))
    assert a == b
