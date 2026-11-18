"""Black out a card number on its photo and draw the last four digits in its place.

The lines are what the page reader found on this image, as fractions of its width and height.
The whole box of the number line is blacked out, with padding above, below and at the sides
(an OCR box is tight and a glyph can reach past it), and the last four digits are drawn as
text inside it. Nothing is cut at a character position, so the font, the letter spacing and
the size of the photo do not matter. A number that the reader split into several lines on one
row (wide gaps between groups) is one number. For an American Express number (34 or 37) any
line that is only four digits is blacked out too, because it is the security code printed on
the front. A line whose digits are the CVV is blacked out. The image given is never changed.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from PIL import Image, ImageDraw, ImageFont

from household_vault.reading.lines import Line

KEEP = 4
MIN_DIGITS = 13
PAD_Y = 0.25  # of the line's height, above and below
PAD_X = 4  # pixels at each side
_AMEX_PREFIXES = ("34", "37")
_BLACK = (0, 0, 0)
_WHITE = (255, 255, 255)
_ROW_OVERLAP = 0.5

Box = tuple[int, int, int, int]


class MaskError(Exception):
    """No line of the page holds the card number, so the photo cannot be masked. The message
    never holds a digit."""


def _digits(text: str) -> str:
    return "".join(c for c in text if c.isdigit())


def padded_box(bbox: tuple[float, float, float, float], size: tuple[int, int]) -> Box:
    """The pixel box blacked out for one line, clipped to the image."""
    width, height = size
    x0, y0, x1, y1 = bbox
    pad = (y1 - y0) * height * PAD_Y
    return (
        max(math.floor(x0 * width) - PAD_X, 0),
        max(math.floor(y0 * height - pad), 0),
        min(math.ceil(x1 * width) + PAD_X, width),
        min(math.ceil(y1 * height + pad), height),
    )


def draw_last_four(image: Image.Image, box: Box, digits: str) -> None:
    """Draw the digits in white at the right end of a box, as large as fits."""
    left, top, right, bottom = box
    draw = ImageDraw.Draw(image)
    margin = max((bottom - top) // 8, 1)
    size = max(int((bottom - top) * 0.6), 8)
    while True:
        font = ImageFont.load_default(size=size)
        left_, t, r, b = draw.textbbox((0, 0), digits, font=font)
        if r - left_ <= right - left - 2 * margin or size <= 8:
            break
        size -= 1
    x = max(right - margin - (r - left_) - left_, left)
    y = top + ((bottom - top) - (b - t)) // 2 - t
    draw.text((x, y), digits, font=font, fill=_WHITE)


def _rows(lines: Sequence[Line]) -> list[list[Line]]:
    """Lines that share a row (their heights overlap by half), left to right."""
    rows: list[list[Line]] = []
    for line in sorted(lines, key=lambda ln: ln.bbox[1]):
        for row in rows:
            top = max(line.bbox[1], row[0].bbox[1])
            bottom = min(line.bbox[3], row[0].bbox[3])
            smaller = min(line.bbox[3] - line.bbox[1], row[0].bbox[3] - row[0].bbox[1])
            if smaller > 0 and (bottom - top) / smaller >= _ROW_OVERLAP:
                row.append(line)
                break
        else:
            rows.append([line])
    return [sorted(row, key=lambda ln: ln.bbox[0]) for row in rows]


def _number_lines(lines: Sequence[Line], wanted: str) -> list[list[Line]]:
    """For each place the number is printed, the lines that hold its digits, left to right."""
    found: list[list[Line]] = []
    for row in _rows([ln for ln in lines if _digits(ln.text)]):
        digits = "".join(_digits(ln.text) for ln in row)
        owner = [i for i, ln in enumerate(row) for _ in _digits(ln.text)]
        start = digits.find(wanted)
        while start >= 0:
            held = sorted(set(owner[start : start + len(wanted)]))
            found.append([row[i] for i in held])
            start = digits.find(wanted, start + len(wanted))
    return found


def mask_card(
    image: Image.Image, lines: Sequence[Line], number: str, cvv: str | None
) -> Image.Image:
    wanted = _digits(number)
    if len(wanted) < MIN_DIGITS:
        raise MaskError("the card number is too short to mask")
    places = _number_lines(lines, wanted)
    if not places:
        raise MaskError("no line of the page holds the card number")
    out = image.convert("RGB").copy()
    draw = ImageDraw.Draw(out)
    in_number = {id(ln) for place in places for ln in place}
    for place in places:
        for ln in place:
            draw.rectangle(padded_box(ln.bbox, out.size), fill=_BLACK)
        last = padded_box(place[-1].bbox, out.size)
        draw_last_four(out, last, wanted[-KEEP:])
    secret = _digits(cvv) if cvv else None
    amex = wanted.startswith(_AMEX_PREFIXES)
    for ln in lines:
        if id(ln) in in_number:
            continue
        digits = _digits(ln.text)
        standalone_cid = amex and len(digits) == KEEP and ln.text.strip() == digits
        if (secret and digits == secret) or standalone_cid:
            draw.rectangle(padded_box(ln.bbox, out.size), fill=_BLACK)
    return out
