import pytest

from household_vault.intake.sniff import EXTENSION, FileKind, sniff

JPEG_HEAD = b"\xff\xd8\xff\xe0\x00\x10JFIF"


@pytest.mark.parametrize(
    ("head", "kind"),
    [
        (JPEG_HEAD, FileKind.jpeg),
        (b"PK\x03\x04", None),
        (b"\x00\x00\x00\x20ftypM4A ", FileKind.audio),
        (b"\x00\x00\x00\x18ftypheic", FileKind.heic),
        (b"\x00\x00\x00\x18ftypmif1", FileKind.heic),
        (b"%PDF-1.7", FileKind.pdf),
        (b"\x89PNG\r\n\x1a\n", FileKind.png),
        (b"ID3\x04", FileKind.audio),
        (b"\xff\xfb\x90", FileKind.audio),
        (b"RIFF\x00\x00\x00\x00WAVEfmt ", FileKind.audio),
        (b"RIFF\x00\x00\x00\x00AVI ", None),
        (b"fLaC", FileKind.audio),
        (b"OggS", FileKind.audio),
        (b"#!AMR\n", FileKind.audio),
        (b"\x00\x00\x00\x18ftypisom", None),
        (b"", None),
    ],
)
def test_kind_comes_from_content_not_the_name(head: bytes, kind: FileKind | None) -> None:
    assert sniff(head) is kind


def test_extensions() -> None:
    assert {
        FileKind.pdf: "pdf",
        FileKind.jpeg: "jpg",
        FileKind.png: "png",
        FileKind.heic: "heic",
    } == EXTENSION
