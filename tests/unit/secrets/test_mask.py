from dataclasses import dataclass

import pytest
from PIL import Image

from household_vault.reading.lines import Line
from household_vault.secrets.mask import MaskError, mask_card

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


def test_mask_blacks_out_all_but_the_last_four(card_photo):
    masked = mask_card(card_photo.image, card_photo.lines, card_photo.number, None)
    assert is_black(masked, card_photo.box_before_last_four)
    assert is_untouched(masked, card_photo.last_four_box)
    assert is_untouched(masked, card_photo.holder_box)
    with pytest.raises(MaskError):
        mask_card(card_photo.image, [], card_photo.number, None)


def test_the_original_image_is_not_changed(card_photo):
    mask_card(card_photo.image, card_photo.lines, card_photo.number, None)
    assert is_untouched(card_photo.image, card_photo.box_before_last_four)


def test_a_number_printed_without_spaces_keeps_its_last_four(card_photo):
    lines = [Line(text=NUMBER, bbox=(0.0, 0.4, 1.0, 0.5))]
    masked = mask_card(card_photo.image, lines, NUMBER, None)
    assert is_black(masked, (0.01, 0.41, 0.74, 0.49))
    assert is_untouched(masked, (0.76, 0.41, 0.99, 0.49))


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
