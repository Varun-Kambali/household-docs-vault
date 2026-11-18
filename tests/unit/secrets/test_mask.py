from dataclasses import dataclass, field

import pytest
from PIL import Image, ImageDraw, ImageFont

from household_vault.reading.lines import Line
from household_vault.secrets.mask import MaskError, draw_last_four, mask_card, padded_box

NUMBER = "4111111111111111"
GREY = (200, 200, 200)


def is_black(image: Image.Image, box: tuple[float, float, float, float]) -> bool:
    """True when every pixel inside the fractional box is black."""
    w, h = image.size
    left, top, right, bottom = (
        round(box[0] * w),
        round(box[1] * h),
        round(box[2] * w),
        round(box[3] * h),
    )
    pixels = image.convert("RGB").crop((left, top, right, bottom)).get_flattened_data()
    return all(p == (0, 0, 0) for p in pixels)


def is_untouched(image: Image.Image, box: tuple[float, float, float, float]) -> bool:
    w, h = image.size
    left, top, right, bottom = (
        round(box[0] * w),
        round(box[1] * h),
        round(box[2] * w),
        round(box[3] * h),
    )
    pixels = image.convert("RGB").crop((left, top, right, bottom)).get_flattened_data()
    return all(p == GREY for p in pixels)


@dataclass
class CardPhoto:
    image: Image.Image
    lines: list[Line]
    number: str
    box_before_last_four: tuple[float, float, float, float]
    last_four_box: tuple[float, float, float, float]
    holder_box: tuple[float, float, float, float]


@pytest.fixture
def card_photo() -> CardPhoto:
    image = Image.new("RGB", (800, 500), GREY)
    text = "4111 1111 1111 1111"
    lines = [
        Line(text=text, bbox=(0.05, 0.40, 0.95, 0.50)),
        Line(text="TEST HOLDER", bbox=(0.05, 0.70, 0.50, 0.78)),
    ]
    start = 15 / len(text)  # the last four digits start at character 15
    edge = 0.05 + 0.90 * start
    return CardPhoto(
        image,
        lines,
        NUMBER,
        box_before_last_four=(0.06, 0.41, edge - 0.01, 0.49),
        last_four_box=(edge + 0.01, 0.41, 0.94, 0.49),
        holder_box=(0.06, 0.71, 0.49, 0.77),
    )


def test_mask_blacks_out_the_whole_number_line_and_draws_the_last_four(card_photo):
    masked = mask_card(card_photo.image, card_photo.lines, card_photo.number, None)
    assert is_black(masked, card_photo.box_before_last_four)
    assert is_untouched(masked, card_photo.holder_box)
    assert reference_last_four(masked, card_photo.lines[0].bbox, "1111")
    with pytest.raises(MaskError):
        mask_card(card_photo.image, [], card_photo.number, None)


def test_the_original_image_is_not_changed(card_photo):
    mask_card(card_photo.image, card_photo.lines, card_photo.number, None)
    assert is_untouched(card_photo.image, card_photo.box_before_last_four)


def test_a_line_that_holds_the_cvv_is_blacked_out(card_photo):
    lines = [*card_photo.lines, Line(text="CVV 737", bbox=(0.05, 0.1, 0.5, 0.2))]
    masked = mask_card(card_photo.image, lines, NUMBER, "737")
    assert is_black(masked, (0.06, 0.11, 0.49, 0.19))
    unmasked = mask_card(card_photo.image, lines, NUMBER, None)
    assert is_untouched(unmasked, (0.06, 0.11, 0.49, 0.19))


def test_a_number_that_is_not_on_the_card_raises(card_photo):
    with pytest.raises(MaskError):
        mask_card(card_photo.image, card_photo.lines, "5555555555554444", None)
    with pytest.raises(MaskError):
        mask_card(card_photo.image, card_photo.lines, "411", None)


def test_the_error_never_holds_the_number(card_photo):
    with pytest.raises(MaskError) as exc:
        mask_card(card_photo.image, [], NUMBER, None)
    assert NUMBER not in str(exc.value) and "1111" not in str(exc.value)


# -- drawn cards: how much of each digit's ink survives -------------------------------------------

INK = (25, 25, 35)
BACK = (226, 224, 214)


@dataclass
class Drawn:
    image: Image.Image
    lines: list[Line]
    digit_ink: list[set[tuple[int, int]]]  # the pixels of each digit of the number, in order
    other_ink: list[set[tuple[int, int]]] = field(default_factory=list)


def _line_of(img: Image.Image, text: str, ink: tuple[int, int, int, int], shrink: int) -> Line:
    w, h = img.size
    left, top, right, bottom = ink
    return Line(
        text=text,
        bbox=(
            (left + shrink) / w,
            (top + shrink) / h,
            (right - shrink) / w,
            (bottom - shrink) / h,
        ),
    )


def draw_number(
    groups: list[str],
    *,
    size: int = 56,
    tracking: int = 0,
    gap: int = 0,
    split_after: int | None = None,
    shrink: int = 0,
    extra: list[tuple[str, tuple[int, int], int]] = (),  # (text, position, size)
) -> Drawn:
    """A card front with the number drawn one character at a time, so each digit's ink is
    known. OCR boxes come from the ink, made `shrink` pixels tighter on every side. With
    `split_after` the number is two lines (the groups before and after that index)."""
    img = Image.new("RGB", (1000, 640), BACK)
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=size)
    x, y = 60, 300
    digit_ink: list[set[tuple[int, int]]] = []
    spans: list[list[tuple[int, int, int, int]]] = [[] for _ in groups]
    for g, group in enumerate(groups):
        if split_after is not None and g == split_after:
            x += 90  # a wide gap between the two lines of one number
        for ch in group:
            layer = Image.new("L", img.size, 0)
            ImageDraw.Draw(layer).text((x, y), ch, font=font, fill=255)
            box = layer.getbbox()
            assert box is not None
            ink = layer.load()
            digit_ink.append(
                {
                    (i, j)
                    for i in range(box[0], box[2])
                    for j in range(box[1], box[3])
                    if ink[i, j] > 128
                }
            )
            d.text((x, y), ch, font=font, fill=INK)
            spans[g].append(box)
            x += font.getlength(ch) + tracking
        x += font.getlength(" ") + tracking + gap

    def union(boxes: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
        return (
            min(b[0] for b in boxes),
            min(b[1] for b in boxes),
            max(b[2] for b in boxes),
            max(b[3] for b in boxes),
        )

    if split_after is None:
        lines = [_line_of(img, " ".join(groups), union([b for g in spans for b in g]), shrink)]
    else:
        first = [b for g in spans[:split_after] for b in g]
        second = [b for g in spans[split_after:] for b in g]
        lines = [
            _line_of(img, " ".join(groups[:split_after]), union(first), shrink),
            _line_of(img, " ".join(groups[split_after:]), union(second), shrink),
        ]
    others = []
    small = ImageFont.load_default(size=28)
    for text, pos, _ in extra:
        layer = Image.new("L", img.size, 0)
        ImageDraw.Draw(layer).text(pos, text, font=small, fill=255)
        box = layer.getbbox()
        assert box is not None
        d.text(pos, text, font=small, fill=INK)
        lines.append(_line_of(img, text, box, 0))
        ink = layer.load()
        others.append(
            {
                (i, j)
                for i in range(box[0], box[2])
                for j in range(box[1], box[3])
                if ink[i, j] > 128
            }
        )
    return Drawn(img, lines, digit_ink, others)


def survivors(masked: Image.Image, ink: set[tuple[int, int]]) -> float:
    """The share of a glyph's ink pixels that are not black in the masked image."""
    data = masked.load()
    return sum(1 for p in ink if data[p] != (0, 0, 0)) / len(ink)


def reference_last_four(masked: Image.Image, bbox, text: str) -> bool:
    """True when the padded box of the line is black with `text` drawn in it by `draw_last_four`
    and nothing else."""
    box = padded_box(bbox, masked.size)
    expected = Image.new("RGB", (box[2] - box[0], box[3] - box[1]), (0, 0, 0))
    draw_last_four(expected, (0, 0, expected.width, expected.height), text)
    return masked.crop(box).tobytes() == expected.tobytes()


def _all_but_last_four_hidden(masked: Image.Image, drawn: Drawn, count: int) -> None:
    for index in range(count - 4):
        assert survivors(masked, drawn.digit_ink[index]) == 0.0, f"digit {index + 1} shows"


@pytest.mark.parametrize(
    ("tracking", "gap", "size"),
    [(0, 0, 56), (-3, 0, 56), (12, 0, 56), (0, 50, 56), (0, 0, 28), (4, 20, 50)],
)
def test_no_digit_but_the_last_four_survives(tracking, gap, size):
    drawn = draw_number(["4111", "1111", "1111", "1111"], size=size, tracking=tracking, gap=gap)
    masked = mask_card(drawn.image, drawn.lines, "4111111111111111", None)
    _all_but_last_four_hidden(masked, drawn, 16)


def test_a_tight_ocr_box_still_covers_the_glyphs():
    drawn = draw_number(["5555", "5555", "5555", "4444"], shrink=4)
    masked = mask_card(drawn.image, drawn.lines, "5555555555554444", None)
    _all_but_last_four_hidden(masked, drawn, 16)


def test_text_touching_the_number_line_is_covered_with_it():
    drawn = draw_number(
        ["4111", "1111", "1111", "1111"],
        shrink=3,
        extra=[("VALID 09/29", (60, 372), 0)],
    )
    masked = mask_card(drawn.image, drawn.lines, "4111111111111111", None)
    _all_but_last_four_hidden(masked, drawn, 16)


def test_a_number_split_across_two_lines_is_one_number():
    drawn = draw_number(["4111", "1111", "1111", "1111"], split_after=2, gap=0)
    assert len(drawn.lines) == 2
    masked = mask_card(drawn.image, drawn.lines, "4111111111111111", None)
    _all_but_last_four_hidden(masked, drawn, 16)


def test_an_amex_number_in_its_own_grouping_and_its_cid_line():
    drawn = draw_number(["3782", "822463", "10005"], extra=[("1234", (800, 150), 0)])
    masked = mask_card(drawn.image, drawn.lines, "378282246310005", None)
    _all_but_last_four_hidden(masked, drawn, 15)
    assert survivors(masked, drawn.other_ink[0]) == 0.0  # the CID


def test_a_four_digit_line_is_left_alone_on_a_card_that_is_not_amex():
    drawn = draw_number(["4111", "1111", "1111", "1111"], extra=[("1234", (800, 150), 0)])
    masked = mask_card(drawn.image, drawn.lines, "4111111111111111", None)
    assert survivors(masked, drawn.other_ink[0]) > 0.9


def test_the_last_four_are_drawn_in_the_box_and_differ_by_digit():
    first = draw_number(["4111", "1111", "1111", "1111"])
    second = draw_number(["4111", "1111", "1111", "1119"])  # not a real card: mask only
    a = mask_card(first.image, first.lines, "4111111111111111", None)
    b = mask_card(second.image, second.lines, "4111111111111119", None)
    assert a.tobytes() != b.tobytes()
    assert reference_last_four(a, first.lines[0].bbox, "1111")
