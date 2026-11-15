"""Decide what a file is from its first bytes. The name is never trusted."""

from enum import StrEnum


class FileKind(StrEnum):
    pdf = "pdf"
    jpeg = "jpeg"
    png = "png"
    heic = "heic"
    audio = "audio"


# Audio keeps its own lowercased suffix, so it has no entry here.
EXTENSION: dict[FileKind, str] = {
    FileKind.pdf: "pdf",
    FileKind.jpeg: "jpg",
    FileKind.png: "png",
    FileKind.heic: "heic",
}

_HEIC_BRANDS = frozenset({b"heic", b"heix", b"heim", b"heis", b"mif1", b"msf1"})
_M4A_BRANDS = frozenset({b"M4A ", b"M4B "})
_MP3_FRAMES = (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")
_AUDIO_STARTS = (b"ID3", b"fLaC", b"OggS", b"#!AMR", *_MP3_FRAMES)


def sniff(head: bytes) -> FileKind | None:
    """The kind of file whose first bytes are head (the first 64 are enough), or None."""
    head = head[:64]
    if head.startswith(b"%PDF-"):
        return FileKind.pdf
    if head.startswith(b"\xff\xd8\xff"):
        return FileKind.jpeg
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return FileKind.png
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in _HEIC_BRANDS:
            return FileKind.heic
        if brand in _M4A_BRANDS:
            return FileKind.audio
        return None
    if head.startswith(b"RIFF") and head[8:12] == b"WAVE":
        return FileKind.audio
    if head.startswith(_AUDIO_STARTS):
        return FileKind.audio
    return None
