"""Zero-dependency EXIF capture-time reader.

A tiny, pure-Python reader that extracts only the capture timestamp
(``DateTimeOriginal``, falling back to ``DateTime``) from a JPEG/TIFF file.
It exists so :meth:`SpectatorDB.insert` can recover a real capture time from a
photo without pulling in Pillow or any other dependency — keeping the core
stdlib-only and fully offline.

This deliberately parses just enough of the EXIF/TIFF structure to find the
timestamp tags. For anything richer (other tags, exotic formats, makernotes),
install the optional ``[exif]`` extra and use a full parser instead.
"""

import struct

from datetime import datetime

import pathlib

# TIFF/EXIF tag numbers.
_TAG_DATETIME = 0x0132  # DateTime (IFD0)
_TAG_EXIF_IFD = 0x8769  # Pointer to the Exif sub-IFD
_TAG_DATETIME_ORIGINAL = 0x9003  # DateTimeOriginal (Exif sub-IFD)

_TYPE_ASCII = 2

__all__ = ["read_captured_at"]


def read_captured_at(path: pathlib.Path) -> datetime | None:
    """Return the EXIF capture time of an image, or ``None`` if unavailable.

    Reads ``DateTimeOriginal`` when present, otherwise ``DateTime``. The
    returned datetime is *naive* (EXIF stores no timezone); callers should
    interpret it in whatever timezone convention they use elsewhere.

    Any malformed, truncated, or non-EXIF file yields ``None`` rather than an
    error, so this is always safe to call as a best-effort fallback.

    Parameters
    ----------
    path : pathlib.Path
        Path to a JPEG (or raw TIFF) file.

    Returns
    -------
    datetime | None
        The capture time, or ``None`` if it could not be read.
    """
    dt = _read_stdlib(path)
    if dt is not None:
        return dt
    # For formats the tiny reader can't handle (e.g. HEIC, unusual layouts),
    # fall back to Pillow if the optional ``[exif]`` extra is installed. The
    # core never imports Pillow, so this stays zero-dependency when it isn't.
    return _read_with_pillow(path)


def _read_stdlib(path: pathlib.Path) -> datetime | None:
    """Read the capture time using only the standard library."""
    try:
        tiff = _extract_tiff(path)
    except OSError:
        return None
    if tiff is None:
        return None

    parsed = _parse_byte_order(tiff)
    if parsed is None:
        return None
    endian, ifd0_offset = parsed

    ifd0 = _read_ifd(tiff, ifd0_offset, endian)

    # Prefer DateTimeOriginal from the Exif sub-IFD.
    exif_ptr = ifd0.get(_TAG_EXIF_IFD)
    if exif_ptr is not None:
        sub_offset = _read_long(tiff, exif_ptr, endian)
        if sub_offset is not None:
            exif_ifd = _read_ifd(tiff, sub_offset, endian)
            original = exif_ifd.get(_TAG_DATETIME_ORIGINAL)
            dt = _parse_datetime(_read_ascii(tiff, original, endian))
            if dt is not None:
                return dt

    # Fall back to IFD0 DateTime.
    return _parse_datetime(_read_ascii(tiff, ifd0.get(_TAG_DATETIME), endian))


def _read_with_pillow(path: pathlib.Path) -> datetime | None:
    """Read the capture time via Pillow, if the ``[exif]`` extra is installed.

    Returns ``None`` when Pillow is absent or cannot parse the file, so callers
    can treat it as a best-effort fallback.
    """
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(path) as image:
            tags = image.getexif()
    except Exception:
        return None

    exif_ifd = tags.get_ifd(_TAG_EXIF_IFD)
    value = exif_ifd.get(_TAG_DATETIME_ORIGINAL) if exif_ifd else None
    if not value:
        value = tags.get(_TAG_DATETIME)
    return _parse_datetime(value if isinstance(value, str) else None)


# Type alias for a parsed IFD entry: (type, count, 4-byte value/offset field).
_Entry = tuple[int, int, bytes]


def _extract_tiff(path: pathlib.Path) -> bytes | None:
    """Return the TIFF block from a JPEG's APP1 EXIF segment, streaming markers.

    Returns raw TIFF bytes (starting at the byte-order mark) or ``None`` if the
    file is not a JPEG or carries no EXIF. If the file is itself a raw TIFF, its
    leading bytes are returned directly.
    """
    with open(path, "rb") as f:
        head = f.read(2)
        if head in (b"II", b"MM"):
            # Raw TIFF file: read a bounded prefix; IFDs live near the front.
            return head + f.read(65536)
        if head != b"\xff\xd8":  # Not a JPEG SOI marker.
            return None

        while True:
            marker = f.read(2)
            if len(marker) < 2 or marker[0] != 0xFF:
                return None
            kind = marker[1]
            # Start of scan / end of image: no more metadata segments.
            if kind in (0xDA, 0xD9):
                return None
            # Standalone markers carry no length payload.
            if kind == 0x01 or 0xD0 <= kind <= 0xD7:
                continue
            length_bytes = f.read(2)
            if len(length_bytes) < 2:
                return None
            (length,) = struct.unpack(">H", length_bytes)
            if length < 2:
                return None
            payload = f.read(length - 2)
            if kind == 0xE1 and payload[:6] == b"Exif\x00\x00":
                return payload[6:]
            # Other segment; keep scanning.


def _parse_byte_order(tiff: bytes) -> tuple[str, int] | None:
    """Return ``(struct_endian, ifd0_offset)`` from a TIFF header, or ``None``."""
    if len(tiff) < 8:
        return None
    order = tiff[:2]
    if order == b"II":
        endian = "<"
    elif order == b"MM":
        endian = ">"
    else:
        return None
    (magic,) = struct.unpack(endian + "H", tiff[2:4])
    if magic != 42:
        return None
    (ifd0_offset,) = struct.unpack(endian + "I", tiff[4:8])
    return endian, ifd0_offset


def _read_ifd(tiff: bytes, offset: int, endian: str) -> dict[int, _Entry]:
    """Parse one IFD into ``{tag: (type, count, value_field)}``."""
    entries: dict[int, _Entry] = {}
    if offset <= 0 or offset + 2 > len(tiff):
        return entries
    (count,) = struct.unpack(endian + "H", tiff[offset : offset + 2])
    pos = offset + 2
    for _ in range(count):
        if pos + 12 > len(tiff):
            break
        tag, typ, cnt = struct.unpack(endian + "HHI", tiff[pos : pos + 8])
        entries[tag] = (typ, cnt, tiff[pos + 8 : pos + 12])
        pos += 12
    return entries


def _read_long(tiff: bytes, entry: _Entry | None, endian: str) -> int | None:
    """Read an entry's value field as an unsigned 32-bit offset."""
    if entry is None:
        return None
    (value,) = struct.unpack(endian + "I", entry[2])
    return int(value)


def _read_ascii(tiff: bytes, entry: _Entry | None, endian: str) -> str | None:
    """Read an ASCII-typed entry's string value, or ``None``."""
    if entry is None:
        return None
    typ, cnt, value_field = entry
    if typ != _TYPE_ASCII or cnt == 0:
        return None
    if cnt <= 4:
        raw = value_field[:cnt]
    else:
        (offset,) = struct.unpack(endian + "I", value_field)
        raw = tiff[offset : offset + cnt]
    return raw.split(b"\x00", 1)[0].decode("ascii", "replace")


def _parse_datetime(text: str | None) -> datetime | None:
    """Parse an EXIF ``YYYY:MM:DD HH:MM:SS`` string into a naive datetime."""
    if not text:
        return None
    try:
        return datetime.strptime(text.strip(), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
