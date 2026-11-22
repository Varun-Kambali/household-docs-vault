"""Page images for the viewer: a PDF page or a photo, as a PNG of a given width.

The image is drawn the way the reader saw it, so the stored line boxes (fractions of the page,
origin top left) land on the same text. PDFs go through `render_page`; photos through
`open_image`, the function the reader used. Drawn pages are kept in memory, least recently used
out first.
"""

import hashlib
import threading
from collections import OrderedDict

from PIL import Image

from household_vault.intake.sniff import FileKind
from household_vault.reading.engines import open_image
from household_vault.reading.render import page_count, png_bytes, render_page

CACHE_PAGES = 64


class NoSuchPage(LookupError):
    """The file has no page with that number."""


_cache: OrderedDict[tuple[str, str, int, int], bytes] = OrderedDict()
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _draw(data: bytes, kind: FileKind, page: int, width: int) -> bytes:
    if page < 0:
        raise NoSuchPage
    if kind is FileKind.pdf:
        if page >= page_count(data):
            raise NoSuchPage
        image = render_page(data, page)
    else:
        if page != 0:
            raise NoSuchPage
        image = open_image(data, kind)
    if image.width != width:
        height = max(1, round(image.height * width / image.width))
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    return png_bytes(image)


def render_png(data: bytes, kind: FileKind, page: int, width: int) -> bytes:
    """The page as PNG bytes, `width` pixels wide with its own proportions."""
    key = (hashlib.sha256(data).hexdigest(), kind.value, page, width)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    out = _draw(data, kind, page, width)
    with _lock:
        _cache[key] = out
        _cache.move_to_end(key)
        while len(_cache) > CACHE_PAGES:
            _cache.popitem(last=False)
    return out
