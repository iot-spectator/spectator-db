"""Tests for the zero-dependency EXIF capture-time reader."""

import pathlib
import struct

from datetime import datetime

import pytest

from spectatordb import exif


def _build_exif_jpeg(datetime_original: str | None) -> bytes:
    """Build a minimal JPEG carrying an EXIF APP1 segment (big-endian TIFF).

    If ``datetime_original`` is ``None``, the Exif sub-IFD is written with no
    entries so the reader must fail gracefully.
    """
    # Exif sub-IFD, laid out at a known offset within the TIFF block.
    # TIFF layout (offsets relative to the byte-order mark):
    #   0  : "MM" + 0x002A + IFD0 offset (8)
    #   8  : IFD0 (1 entry -> Exif IFD pointer)
    #   26 : Exif sub-IFD
    #   ...: DateTimeOriginal string payload
    exif_ifd_offset = 26

    if datetime_original is not None:
        string_bytes = datetime_original.encode("ascii") + b"\x00"
        string_offset = exif_ifd_offset + 2 + 12 + 4  # count + entry + next-ptr
        exif_ifd = struct.pack(">H", 1)  # one entry
        exif_ifd += struct.pack(
            ">HHI", exif._TAG_DATETIME_ORIGINAL, 2, len(string_bytes)
        )
        exif_ifd += struct.pack(">I", string_offset)
        exif_ifd += struct.pack(">I", 0)  # next IFD = none
        exif_ifd += string_bytes
    else:
        exif_ifd = struct.pack(">H", 0) + struct.pack(">I", 0)

    tiff = b"MM" + struct.pack(">H", 42) + struct.pack(">I", 8)
    ifd0 = struct.pack(">H", 1)  # one entry: Exif IFD pointer
    ifd0 += struct.pack(">HHI", exif._TAG_EXIF_IFD, 4, 1)
    ifd0 += struct.pack(">I", exif_ifd_offset)
    ifd0 += struct.pack(">I", 0)  # next IFD = none
    tiff += ifd0 + exif_ifd

    payload = b"Exif\x00\x00" + tiff
    app1 = b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    # SOI + APP1 + a token SOS/EOI so it looks like a real JPEG tail.
    return b"\xff\xd8" + app1 + b"\xff\xda\x00\x02\xff\xd9"


def test_reads_datetime_original(tmp_path: pathlib.Path) -> None:
    img = tmp_path / "photo.jpg"
    img.write_bytes(_build_exif_jpeg("2021:07:15 09:30:00"))
    assert exif.read_captured_at(img) == datetime(2021, 7, 15, 9, 30, 0)


def test_missing_timestamp_returns_none(tmp_path: pathlib.Path) -> None:
    img = tmp_path / "photo.jpg"
    img.write_bytes(_build_exif_jpeg(None))
    assert exif.read_captured_at(img) is None


def test_non_jpeg_returns_none(tmp_path: pathlib.Path) -> None:
    f = tmp_path / "notes.txt"
    f.write_bytes(b"just some text, definitely not a jpeg")
    assert exif.read_captured_at(f) is None


def test_missing_file_returns_none(tmp_path: pathlib.Path) -> None:
    assert exif.read_captured_at(tmp_path / "nope.jpg") is None


@pytest.mark.parametrize("garbage", [b"", b"\xff\xd8", b"\xff\xd8\xff\xe1\x00"])
def test_truncated_files_return_none(tmp_path: pathlib.Path, garbage: bytes) -> None:
    img = tmp_path / "trunc.jpg"
    img.write_bytes(garbage)
    assert exif.read_captured_at(img) is None
