"""A personal photo and video library, built on spectator-db.

This is a complete, working command-line tool in a single file. It shows the
whole library surface end to end: bulk import with deduplication, tagging,
composable search by time/type/label/device, similarity search, export, and
maintenance.

The core is stdlib-only, exactly like the library itself. The one exception is
``embed``, which needs an image decoder and so requires Pillow::

    $ python -m pip install "spectator-db[exif]"

Everything else runs with no dependencies at all.

A library is just two things on disk — a folder of media files and one SQLite
catalog::

    <library>/media/        the media files, named by record id
    <library>/catalog.db    the metadata catalog

Examples
--------
::

    $ python photos.py import ~/Pictures
    $ python photos.py list --type image --since 2026-01-01
    $ python photos.py tag <id> --add beach --add sunset
    $ python photos.py list --label beach
    $ python photos.py embed
    $ python photos.py similar <id>
    $ python photos.py export <id> ./out.jpg
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import tempfile

from dataclasses import dataclass
from datetime import datetime, timezone

from spectatordb import (
    LocalStorage,
    MediaRecord,
    MediaType,
    SpectatorDB,
    SQLiteMetadataStore,
)

DEFAULT_LIBRARY = pathlib.Path.home() / ".spectator-photos"

# Identity of the vectors written by ``embed``. Similarity search is scoped to a
# single model, so changing this scheme means re-running ``embed --force``.
EMBEDDING_MODEL = "colorlayout-v1"

_THUMB_SIZE = 32
_GRID = 4
_LUMA_BINS = 16


# ----------------------------------------------------------------------
# Library plumbing
# ----------------------------------------------------------------------


def open_library(root: pathlib.Path) -> SpectatorDB:
    """Open (creating if needed) the library rooted at ``root``.

    Parameters
    ----------
    root : pathlib.Path
        The library directory.

    Returns
    -------
    SpectatorDB
        A store backed by ``root/media`` and ``root/catalog.db``.
    """
    root.mkdir(parents=True, exist_ok=True)
    return SpectatorDB(
        storage=LocalStorage(root / "media"),
        metadata_store=SQLiteMetadataStore(root / "catalog.db"),
    )


def _parse_when(value: str) -> datetime:
    """Parse a ``YYYY-MM-DD`` date or an ISO-8601 timestamp into UTC.

    Parameters
    ----------
    value : str
        The date or timestamp to parse.

    Returns
    -------
    datetime
        A timezone-aware UTC datetime.

    Raises
    ------
    argparse.ArgumentTypeError
        If ``value`` is not a recognized date or timestamp.
    """
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"not a date or timestamp: {value!r}"
            " (expected YYYY-MM-DD or an ISO-8601 timestamp)"
        ) from None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass
class _Filters:
    """The query filters shared by ``list`` and ``count``.

    Parameters
    ----------
    start : datetime | None
        Include records captured at or after this time.
    end : datetime | None
        Include records captured before this time.
    media_type : MediaType | None
        Restrict to one media type.
    device_id : str | None
        Restrict to one capturing device.
    labels : list[str] | None
        Restrict to records carrying any of these labels.
    """

    start: datetime | None = None
    end: datetime | None = None
    media_type: MediaType | None = None
    device_id: str | None = None
    labels: list[str] | None = None


def _filters(args: argparse.Namespace) -> _Filters:
    """Read the shared filter options off the parsed arguments.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments carrying the filter options.

    Returns
    -------
    _Filters
        The filters to hand to ``query`` and ``count``.
    """
    return _Filters(
        start=args.since,
        end=args.until,
        media_type=MediaType(args.type) if args.type else None,
        device_id=args.device,
        labels=args.label or None,
    )


def _format_row(record: MediaRecord) -> str:
    """Render one record as a single aligned line.

    Parameters
    ----------
    record : MediaRecord
        The record to render.

    Returns
    -------
    str
        A line with id, capture time, type, size, and labels.
    """
    when = record.captured_at.strftime("%Y-%m-%d %H:%M")
    size = _format_size(record.size)
    labels = ",".join(record.labels) if record.labels else "-"
    marker = "*" if record.embedding is not None else " "
    return (
        f"{record.id[:8]}{marker} {when}  {record.media_type.value:<5}"
        f" {size:>9}  {labels}"
    )


def _format_size(num_bytes: int) -> str:
    """Render a byte count in human-readable units.

    Parameters
    ----------
    num_bytes : int
        The size in bytes.

    Returns
    -------
    str
        The size with a unit suffix, e.g. ``1.4 MB``.
    """
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _resolve_id(db: SpectatorDB, prefix: str) -> str:
    """Resolve a record-id prefix to exactly one full id.

    Listings abbreviate ids to eight characters, so accept that as input.

    Parameters
    ----------
    db : SpectatorDB
        The open library.
    prefix : str
        A full id or a unique leading fragment of one.

    Returns
    -------
    str
        The single matching record id.

    Raises
    ------
    SystemExit
        If the prefix matches no records or more than one.
    """
    matches = [r.id for r in db.query() if r.id.startswith(prefix)]
    if not matches:
        raise SystemExit(f"error: no record matches id {prefix!r}")
    if len(matches) > 1:
        joined = ", ".join(m[:8] for m in matches[:5])
        raise SystemExit(f"error: id {prefix!r} is ambiguous ({joined})")
    return matches[0]


# ----------------------------------------------------------------------
# Color-layout embedding
# ----------------------------------------------------------------------


def _l2_normalize(vector: list[float]) -> list[float]:
    """Scale a vector to unit length, leaving an all-zero vector unchanged.

    Parameters
    ----------
    vector : list[float]
        The vector to normalize.

    Returns
    -------
    list[float]
        The unit-length vector.
    """
    norm = sum(value * value for value in vector) ** 0.5
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def _color_layout_embedding(path: pathlib.Path) -> list[float]:
    """Compute a 64-dimensional color-layout signature for an image.

    The signature is the mean RGB of each cell of a 4x4 grid (48 values)
    concatenated with a 16-bin luma histogram, L2-normalized so that cosine
    similarity is meaningful.

    This is deliberately simple and honest about what it is: it matches images
    by color and composition, **not** by meaning. Two different red cars score
    highly; a car and a photo of the word "car" do not. Swapping in a real
    model such as CLIP means changing this function and ``EMBEDDING_MODEL`` —
    the storage and search path stay exactly the same.

    Parameters
    ----------
    path : pathlib.Path
        Path to a decodable image file.

    Returns
    -------
    list[float]
        A unit-length vector of length 64.

    Raises
    ------
    SystemExit
        If Pillow is not installed.
    """
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit(
            "error: embed requires an image decoder.\n"
            '       python -m pip install "spectator-db[exif]"'
        ) from None

    with Image.open(path) as handle:
        thumb = handle.convert("RGB").resize((_THUMB_SIZE, _THUMB_SIZE))
        # Three bytes per pixel, row-major. tobytes() is stable across Pillow
        # versions, unlike getdata(), which is deprecated in Pillow 14.
        raw = bytes(thumb.tobytes())

    cell = _THUMB_SIZE // _GRID
    cells = _GRID * _GRID
    sums = [[0.0, 0.0, 0.0] for _ in range(cells)]
    counts = [0] * cells
    luma = [0.0] * _LUMA_BINS
    pixel_count = len(raw) // 3

    for index in range(pixel_count):
        offset = index * 3
        red = float(raw[offset])
        green = float(raw[offset + 1])
        blue = float(raw[offset + 2])
        row, column = divmod(index, _THUMB_SIZE)
        target = (row // cell) * _GRID + (column // cell)
        sums[target][0] += red
        sums[target][1] += green
        sums[target][2] += blue
        counts[target] += 1
        brightness = 0.299 * red + 0.587 * green + 0.114 * blue
        bucket = min(int(brightness / 256 * _LUMA_BINS), _LUMA_BINS - 1)
        luma[bucket] += 1.0

    vector: list[float] = []
    for index in range(cells):
        divisor = counts[index] or 1
        vector.extend(channel / divisor / 255.0 for channel in sums[index])
    total = pixel_count or 1
    vector.extend(count / total for count in luma)
    return _l2_normalize(vector)


# ----------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------


def cmd_import(db: SpectatorDB, args: argparse.Namespace) -> int:
    """Bulk-import a folder of media.

    Parameters
    ----------
    db : SpectatorDB
        The open library.
    args : argparse.Namespace
        Parsed arguments.

    Returns
    -------
    int
        Process exit status.
    """
    source = args.directory.expanduser()
    if not source.is_dir():
        raise SystemExit(f"error: not a directory: {source}")

    ids = db.import_dir(
        source,
        recursive=not args.no_recursive,
        skip_duplicates=not args.allow_duplicates,
        device_id=args.device,
    )
    print(f"imported {len(ids)} file(s) from {source}")
    print(f"library now holds {db.count()} record(s)")
    return 0


def cmd_list(db: SpectatorDB, args: argparse.Namespace) -> int:
    """List records matching the filters, newest first.

    Parameters
    ----------
    db : SpectatorDB
        The open library.
    args : argparse.Namespace
        Parsed arguments.

    Returns
    -------
    int
        Process exit status.
    """
    filters = _filters(args)
    total = db.count(
        start=filters.start,
        end=filters.end,
        media_type=filters.media_type,
        device_id=filters.device_id,
        labels=filters.labels,
    )
    records = db.query(
        start=filters.start,
        end=filters.end,
        media_type=filters.media_type,
        device_id=filters.device_id,
        labels=filters.labels,
        limit=args.limit,
        offset=args.offset,
    )
    if not records:
        print("no matching records")
        return 0
    for record in records:
        print(_format_row(record))
    shown = len(records)
    suffix = f" (of {total})" if shown != total else ""
    legend = (
        "   * = has an embedding"
        if any(record.embedding is not None for record in records)
        else ""
    )
    print(f"\n{shown} record(s){suffix}{legend}")
    return 0


def cmd_show(db: SpectatorDB, args: argparse.Namespace) -> int:
    """Print every field of a single record.

    Parameters
    ----------
    db : SpectatorDB
        The open library.
    args : argparse.Namespace
        Parsed arguments.

    Returns
    -------
    int
        Process exit status.
    """
    record = db.get(_resolve_id(db, args.id))
    fields: list[tuple[str, str]] = [
        ("id", record.id),
        ("type", record.media_type.value),
        ("format", record.format),
        ("size", _format_size(record.size)),
        ("captured", record.captured_at.isoformat()),
        ("inserted", record.inserted_at.isoformat() if record.inserted_at else "-"),
        ("duration", f"{record.duration:.1f}s" if record.duration else "-"),
        ("device", record.device_id or "-"),
        ("labels", ", ".join(record.labels) or "-"),
        ("description", record.description or "-"),
        ("hash", record.content_hash or "-"),
        (
            "embedding",
            (
                f"{record.embedding_dim}d via {record.embedding_model}"
                if record.embedding
                else "-"
            ),
        ),
    ]
    for name, value in fields:
        print(f"{name:>12}  {value}")
    return 0


def cmd_tag(db: SpectatorDB, args: argparse.Namespace) -> int:
    """Add or remove labels, and optionally set a description.

    Parameters
    ----------
    db : SpectatorDB
        The open library.
    args : argparse.Namespace
        Parsed arguments.

    Returns
    -------
    int
        Process exit status.
    """
    record_id = _resolve_id(db, args.id)
    record = db.get(record_id)

    labels = list(record.labels)
    for label in args.add or []:
        if label not in labels:
            labels.append(label)
    for label in args.remove or []:
        if label in labels:
            labels.remove(label)

    if args.describe is not None:
        db.update_enrichment(record_id, labels=labels, description=args.describe)
    else:
        db.update_enrichment(record_id, labels=labels)

    print(f"{record_id[:8]}  labels: {', '.join(labels) or '-'}")
    return 0


def cmd_embed(db: SpectatorDB, args: argparse.Namespace) -> int:
    """Compute and store color-layout embeddings for images.

    Parameters
    ----------
    db : SpectatorDB
        The open library.
    args : argparse.Namespace
        Parsed arguments.

    Returns
    -------
    int
        Process exit status.
    """
    records = db.query(media_type=MediaType.IMAGE)
    pending = [
        record
        for record in records
        if args.force or record.embedding_model != EMBEDDING_MODEL
    ]
    if not pending:
        print(f"nothing to do: {len(records)} image(s) already embedded")
        return 0

    print(f"embedding {len(pending)} image(s) with {EMBEDDING_MODEL}...")
    failed = 0
    with tempfile.TemporaryDirectory() as workspace:
        scratch = pathlib.Path(workspace)
        for record in pending:
            staged = scratch / f"{record.id}.{record.format}"
            try:
                db.retrieve(record.id, staged)
                vector = _color_layout_embedding(staged)
            except SystemExit:
                raise
            except Exception as error:  # noqa: BLE001 - report and keep going
                failed += 1
                print(f"  skipped {record.id[:8]}: {error}", file=sys.stderr)
                continue
            finally:
                staged.unlink(missing_ok=True)
            db.update_enrichment(
                record.id,
                embedding=vector,
                embedding_model=EMBEDDING_MODEL,
            )

    print(f"embedded {len(pending) - failed} image(s), {failed} skipped")
    return 0


def cmd_similar(db: SpectatorDB, args: argparse.Namespace) -> int:
    """Find records visually similar to the given one.

    Parameters
    ----------
    db : SpectatorDB
        The open library.
    args : argparse.Namespace
        Parsed arguments.

    Returns
    -------
    int
        Process exit status.
    """
    record = db.get(_resolve_id(db, args.id))
    if record.embedding is None or record.embedding_model is None:
        raise SystemExit(
            f"error: {record.id[:8]} has no embedding — run 'photos.py embed' first"
        )

    matches = db.search_similar(
        record.embedding,
        model=record.embedding_model,
        limit=args.limit + 1,
        threshold=args.threshold,
    )
    neighbors = [match for match in matches if match.id != record.id][: args.limit]
    if not neighbors:
        print("no similar records found")
        return 0

    print(f"most similar to {record.id[:8]}:")
    for neighbor in neighbors:
        print(f"  {_format_row(neighbor)}")
    return 0


def cmd_export(db: SpectatorDB, args: argparse.Namespace) -> int:
    """Copy a stored media file back out to a destination path.

    Parameters
    ----------
    db : SpectatorDB
        The open library.
    args : argparse.Namespace
        Parsed arguments.

    Returns
    -------
    int
        Process exit status.
    """
    record_id = _resolve_id(db, args.id)
    destination = args.destination.expanduser()
    if destination.is_dir():
        record = db.get(record_id)
        destination = destination / f"{record.id}.{record.format}"
    db.retrieve(record_id, destination)
    print(f"wrote {destination}")
    return 0


def cmd_delete(db: SpectatorDB, args: argparse.Namespace) -> int:
    """Delete a record and its backing file.

    Parameters
    ----------
    db : SpectatorDB
        The open library.
    args : argparse.Namespace
        Parsed arguments.

    Returns
    -------
    int
        Process exit status.
    """
    record_id = _resolve_id(db, args.id)
    db.delete(record_id)
    print(f"deleted {record_id[:8]}")
    return 0


def cmd_stats(db: SpectatorDB, args: argparse.Namespace) -> int:
    """Summarize what the library holds.

    Parameters
    ----------
    db : SpectatorDB
        The open library.
    args : argparse.Namespace
        Parsed arguments.

    Returns
    -------
    int
        Process exit status.
    """
    total = db.count()
    if total == 0:
        print("library is empty")
        return 0

    images = db.count(media_type=MediaType.IMAGE)
    videos = db.count(media_type=MediaType.VIDEO)
    records = db.query()
    stored = sum(record.size for record in records)
    embedded = sum(1 for record in records if record.embedding is not None)
    labels: dict[str, int] = {}
    for record in records:
        for label in record.labels:
            labels[label] = labels.get(label, 0) + 1

    oldest = min(record.captured_at for record in records)
    newest = max(record.captured_at for record in records)

    print(f"     records  {total} ({images} image, {videos} video)")
    print(f"       bytes  {_format_size(stored)}")
    print(f"  embeddings  {embedded}/{images} image(s)")
    print(f"        span  {oldest.date()} to {newest.date()}")
    if labels:
        ranked = sorted(labels.items(), key=lambda item: (-item[1], item[0]))
        rendered = ", ".join(f"{name} ({count})" for name, count in ranked[:10])
        print(f"      labels  {rendered}")
    return 0


def cmd_reconcile(db: SpectatorDB, args: argparse.Namespace) -> int:
    """Sweep out orphaned files and dangling catalog rows.

    Parameters
    ----------
    db : SpectatorDB
        The open library.
    args : argparse.Namespace
        Parsed arguments.

    Returns
    -------
    int
        Process exit status.
    """
    report = db.reconcile()
    print(f"deleted {report.deleted_files} orphaned file(s)")
    print(f"deleted {report.deleted_rows} dangling row(s)")
    return 0


# ----------------------------------------------------------------------
# Argument parsing
# ----------------------------------------------------------------------


def _add_filter_options(parser: argparse.ArgumentParser) -> None:
    """Attach the shared query-filter options to a subparser.

    Parameters
    ----------
    parser : argparse.ArgumentParser
        The subparser to extend.
    """
    parser.add_argument(
        "--since", type=_parse_when, help="only records captured at or after this time"
    )
    parser.add_argument(
        "--until", type=_parse_when, help="only records captured before this time"
    )
    parser.add_argument(
        "--type", choices=[media.value for media in MediaType], help="filter by type"
    )
    parser.add_argument("--device", help="filter by device id")
    parser.add_argument(
        "--label",
        action="append",
        help="filter by label; repeatable, any-match",
    )


def build_parser() -> argparse.ArgumentParser:
    """Construct the command-line parser.

    Returns
    -------
    argparse.ArgumentParser
        The fully configured parser.
    """
    parser = argparse.ArgumentParser(
        prog="photos.py",
        description="A personal photo and video library, built on spectator-db.",
    )
    parser.add_argument(
        "--library",
        type=pathlib.Path,
        default=DEFAULT_LIBRARY,
        help=f"library directory (default: {DEFAULT_LIBRARY})",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    importer = subparsers.add_parser("import", help="import a folder of media")
    importer.add_argument("directory", type=pathlib.Path)
    importer.add_argument(
        "--no-recursive", action="store_true", help="do not descend into subfolders"
    )
    importer.add_argument(
        "--allow-duplicates",
        action="store_true",
        help="import files whose content hash is already present",
    )
    importer.add_argument("--device", help="tag every imported record with this device")
    importer.set_defaults(handler=cmd_import)

    lister = subparsers.add_parser("list", help="list records, newest first")
    _add_filter_options(lister)
    lister.add_argument("--limit", type=int, default=20, help="default: 20")
    lister.add_argument("--offset", type=int, default=0)
    lister.set_defaults(handler=cmd_list)

    shower = subparsers.add_parser("show", help="show one record in full")
    shower.add_argument("id", help="record id, or a unique prefix of one")
    shower.set_defaults(handler=cmd_show)

    tagger = subparsers.add_parser("tag", help="add or remove labels")
    tagger.add_argument("id", help="record id, or a unique prefix of one")
    tagger.add_argument("--add", action="append", help="label to add; repeatable")
    tagger.add_argument("--remove", action="append", help="label to remove; repeatable")
    tagger.add_argument("--describe", help="set the description")
    tagger.set_defaults(handler=cmd_tag)

    embedder = subparsers.add_parser(
        "embed",
        help="compute color-layout embeddings for images (requires Pillow)",
    )
    embedder.add_argument(
        "--force", action="store_true", help="recompute embeddings that already exist"
    )
    embedder.set_defaults(handler=cmd_embed)

    finder = subparsers.add_parser("similar", help="find visually similar records")
    finder.add_argument("id", help="record id, or a unique prefix of one")
    finder.add_argument("--limit", type=int, default=5, help="default: 5")
    finder.add_argument("--threshold", type=float, help="minimum cosine similarity")
    finder.set_defaults(handler=cmd_similar)

    exporter = subparsers.add_parser("export", help="copy a media file back out")
    exporter.add_argument("id", help="record id, or a unique prefix of one")
    exporter.add_argument("destination", type=pathlib.Path)
    exporter.set_defaults(handler=cmd_export)

    deleter = subparsers.add_parser("delete", help="delete a record and its file")
    deleter.add_argument("id", help="record id, or a unique prefix of one")
    deleter.set_defaults(handler=cmd_delete)

    stats = subparsers.add_parser("stats", help="summarize the library")
    stats.set_defaults(handler=cmd_stats)

    reconciler = subparsers.add_parser(
        "reconcile", help="sweep orphaned files and dangling rows"
    )
    reconciler.set_defaults(handler=cmd_reconcile)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the command-line tool.

    Parameters
    ----------
    argv : list[str] | None
        Argument vector; defaults to ``sys.argv[1:]``.

    Returns
    -------
    int
        Process exit status.
    """
    args = build_parser().parse_args(argv)
    with open_library(args.library.expanduser()) as db:
        result = args.handler(db, args)
    return int(result)


if __name__ == "__main__":
    sys.exit(main())
