"""Black out a card number on its photo, leaving the last four digits.

The lines are what the page reader found on this image, as fractions of its width and height.
The line that holds the number is blacked out up to the character where the last four digits
start (measured by character position, so the cut is exact for a line of even letter widths and
near it otherwise). A line whose digits are the CVV is blacked out whole. The image given is
never changed; a masked copy comes back.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from PIL import Image, ImageDraw

from household_vault.reading.lines import Line

KEEP = 4
MIN_DIGITS = 13


class MaskError(Exception):
    """No line of the page holds the card number, so the photo cannot be masked. The message
    never holds a digit."""


def _digits(text: str) -> str:
    return "".join(c for c in text if c.isdigit())


def mask_card(
    image: Image.Image, lines: Sequence[Line], number: str, cvv: str | None
) -> Image.Image:
    wanted = _digits(number)
    if len(wanted) < MIN_DIGITS:
        raise MaskError("the card number is too short to mask")
    out = image.convert("RGB").copy()
    draw = ImageDraw.Draw(out)
    width, height = out.size
    found = False
    for line in lines:
        positions = [i for i, c in enumerate(line.text) if c.isdigit()]
        joined = "".join(line.text[i] for i in positions)
        x0, y0, x1, y1 = line.bbox
        at = joined.find(wanted)
        if at >= 0:
            found = True
            cut = positions[at + len(wanted) - KEEP]  # the character where the last four start
            x1 = x0 + (x1 - x0) * (cut / len(line.text))
        elif not (cvv and joined == _digits(cvv)):
            continue
        box = (
            math.floor(x0 * width),
            math.floor(y0 * height),
            max(math.ceil(x1 * width) - 1, math.floor(x0 * width)),
            math.ceil(y1 * height) - 1,
        )
        draw.rectangle(box, fill=(0, 0, 0))
    if not found:
        raise MaskError("no line of the page holds the card number")
    return out
