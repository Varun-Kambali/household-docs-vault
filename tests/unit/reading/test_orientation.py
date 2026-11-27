"""A photo carries its orientation in an EXIF tag. Every reader sees it upright."""

import io

import pytest
from PIL import Image

from household_vault.intake.sniff import FileKind
from household_vault.pages import clear_cache, render_png
from household_vault.reading.engines import open_image, upright_bytes
from household_vault.reading.lines import Line
from household_vault.secrets.mask import mask_card

ORIENTATION = 0x0112


def upright() -> Image.Image:
    """800 x 500, grey, with a white block at the top left and a black one at the bottom right."""
    img = Image.new("RGB", (800, 500), (128, 128, 128))
    img.paste((255, 255, 255), (0, 0, 80, 50))
    img.paste((0, 0, 0), (720, 450, 800, 500))
    return img


# stored pixels that show the upright picture once the tag is applied
STORED = {
    1: lambda im: im,
    3: lambda im: im.rotate(180),
    6: lambda im: im.rotate(90, expand=True),  # displayed by turning 90 degrees clockwise
    8: lambda im: im.rotate(-90, expand=True),
}


def photo(orientation: int, fmt: str = "PNG") -> bytes:
    exif = Image.Exif()
    exif[ORIENTATION] = orientation
    buf = io.BytesIO()
    STORED[orientation](upright()).save(buf, format=fmt, exif=exif)
    return buf.getvalue()


@pytest.mark.parametrize("orientation", [1, 3, 6, 8])
def test_open_image_returns_the_upright_picture(orientation):
    got = open_image(photo(orientation), FileKind.png)
    assert got.size == (800, 500)
    assert got.getpixel((10, 10)) == (255, 255, 255)
    assert got.getpixel((790, 490)) == (0, 0, 0)


def test_a_jpeg_with_a_rotation_tag_opens_upright():
    got = open_image(photo(6, "JPEG"), FileKind.jpeg)
    assert got.size == (800, 500)


def test_a_photo_with_no_tag_is_read_as_stored():
    buf = io.BytesIO()
    upright().save(buf, format="PNG")
    assert open_image(buf.getvalue(), FileKind.png).size == (800, 500)


def test_upright_bytes_leaves_an_untagged_photo_alone_and_turns_a_tagged_one():
    plain = io.BytesIO()
    upright().save(plain, format="PNG")
    assert upright_bytes(plain.getvalue()) == plain.getvalue()
    tagged = photo(6)
    assert upright_bytes(tagged) != tagged
    with Image.open(io.BytesIO(upright_bytes(tagged))) as img:
        assert img.size == (800, 500)
        assert img.getexif().get(ORIENTATION, 1) == 1
    assert upright_bytes(b"not an image") == b"not an image"


def test_the_viewer_draws_the_upright_page_at_its_proportions():
    clear_cache()
    out = render_png(photo(6), FileKind.png, 0, 400)
    with Image.open(io.BytesIO(out)) as img:
        assert img.size == (400, 250)
        assert img.getpixel((5, 5)) == (255, 255, 255)


def test_a_card_photo_with_a_rotation_tag_is_masked_where_its_number_is():
    image = open_image(photo(6), FileKind.png)
    lines = [Line(text="4111 1111 1111 1111", bbox=(0.05, 0.40, 0.95, 0.50))]
    masked = mask_card(image, lines, "4111111111111111", None)
    w, h = masked.size
    band = masked.crop((round(0.06 * w), round(0.41 * h), round(0.65 * w), round(0.49 * h)))
    assert all(p == (0, 0, 0) for p in band.get_flattened_data())
    assert masked.getpixel((10, 10)) == (255, 255, 255)  # the rest is untouched


def test_the_vision_model_gets_the_upright_photo():
    from household_vault.intake.sniff import FileKind as Kind
    from household_vault.reading.pipeline import _fill_images
    from household_vault.reading.source import DocumentSource

    plain = io.BytesIO()
    upright().save(plain, format="PNG")
    sent = _fill_images(DocumentSource(Kind.png, data=photo(6)), None)
    with Image.open(io.BytesIO(sent[0])) as img:
        assert img.size == (800, 500)
    untagged = _fill_images(DocumentSource(Kind.png, data=plain.getvalue()), None)
    assert untagged == [plain.getvalue()]


def test_a_turned_photo_goes_back_as_a_high_quality_jpeg_not_a_png():
    out = upright_bytes(photo(6, "JPEG"))
    with Image.open(io.BytesIO(out)) as img:
        assert img.format == "JPEG" and img.size == (800, 500)
        assert img.getexif().get(ORIENTATION, 1) == 1
        assert all(c > 240 for c in img.getpixel((5, 5)))  # the white block, top left
        assert all(c < 15 for c in img.getpixel((795, 495)))  # the black block, bottom right
        quant = img.quantization[0]
        assert max(quant) <= 16  # the standard table scaled for quality 92 tops out at 16
