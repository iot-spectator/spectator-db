"""Reproducible benchmarks for spectator-db.

Measures the three numbers that set honest expectations for the library:
insert throughput, similarity-search latency, and on-disk size, at a range
of library sizes.

The harness is stdlib-only, exactly like the core it measures, so the same
script runs unmodified on a laptop and on a Raspberry Pi::

    $ python benchmarks/benchmark.py --scales 1000,10000
    $ python benchmarks/benchmark.py --scales 1000,10000,50000 --json out.json

What is actually being timed
----------------------------
``insert()`` is timed end to end: SHA-256 of the file, the copy into storage,
and the SQLite row with its commit. Source files are written *outside* the
timed region, so file generation never counts toward the result. Because the
hash and the copy both scale with file size, every insert number is only
meaningful next to the file size that produced it — ``--file-size-sweep``
measures that relationship directly.

``search_similar()`` is pure-Python brute force by design: every vector for
the model is loaded, JSON-decoded, and scored. It is O(N) in the number of
stored vectors, and ``limit`` is applied *after* scoring, so it bounds the
result list but not the work. That is the cost this table is here to expose.

Caveats that keep the numbers honest
------------------------------------
Every measurement is warm: the process, the page cache, and the SQLite
connection are all hot by the time timing starts. A first query after boot
will be slower. Timings come from ``time.perf_counter`` around single
operations, reported as median and p95 rather than a mean, because the
commit-per-insert tail is the part that bites. Capture times are passed
explicitly, so the EXIF path is deliberately excluded — synthetic files carry
no EXIF and timing the fallback would flatter the result.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import platform
import random
import shutil
import sqlite3
import statistics
import sys
import tempfile
import time

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from spectatordb import (
    LocalStorage,
    MediaType,
    SpectatorDB,
    SQLiteMetadataStore,
)

# Identity for the vectors written during the enrich phase. Similarity search
# is scoped to a single model, so this only has to be internally consistent.
EMBEDDING_MODEL = "benchmark-v1"

# Devices and labels are spread across the corpus so the indexed-read phase
# filters on something real rather than matching every row.
_DEVICES = ("pi-front-door", "pi-garage", "pi-garden")
_LABELS = ("person", "car", "cat", "package")

_DEFAULT_SCALES = (1000, 10000, 50000)


# ----------------------------------------------------------------------
# Timing helpers
# ----------------------------------------------------------------------


@dataclass
class Timings:
    """Summary statistics for one series of timed operations."""

    count: int
    total_s: float
    median_ms: float
    p95_ms: float
    min_ms: float
    max_ms: float
    ops_per_s: float


def _percentile(sorted_samples: list[float], fraction: float) -> float:
    """Return the nearest-rank percentile of an already-sorted series."""
    if not sorted_samples:
        return 0.0
    rank = max(1, min(len(sorted_samples), round(fraction * len(sorted_samples))))
    return sorted_samples[rank - 1]


def _summarize(samples: list[float]) -> Timings:
    """Reduce per-operation durations (in seconds) to summary statistics."""
    if not samples:
        return Timings(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    ordered = sorted(samples)
    total = sum(samples)
    return Timings(
        count=len(samples),
        total_s=total,
        median_ms=statistics.median(ordered) * 1000,
        p95_ms=_percentile(ordered, 0.95) * 1000,
        min_ms=ordered[0] * 1000,
        max_ms=ordered[-1] * 1000,
        ops_per_s=(len(samples) / total) if total > 0 else 0.0,
    )


# ----------------------------------------------------------------------
# Corpus generation
# ----------------------------------------------------------------------


def _unit_vector(dim: int, rng: random.Random) -> list[float]:
    """Return a random L2-normalized vector of the given dimension."""
    values = [rng.gauss(0.0, 1.0) for _ in range(dim)]
    norm = sum(v * v for v in values) ** 0.5
    if norm == 0.0:
        return [0.0] * dim
    return [v / norm for v in values]


def _open_db(root: pathlib.Path) -> SpectatorDB:
    """Open a fresh library rooted at the given directory."""
    storage = LocalStorage(root / "media")
    metadata_store = SQLiteMetadataStore(root / "catalog.db")
    return SpectatorDB(storage, metadata_store)


def _catalog_bytes(db_path: pathlib.Path) -> int:
    """Return the catalog's on-disk size, checkpointing the WAL first.

    Without the checkpoint most recent writes still live in the ``-wal``
    sidecar and the main file understates the true footprint.
    """
    connection = sqlite3.connect(str(db_path))
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()

    total = 0
    for suffix in ("", "-wal", "-shm"):
        path = pathlib.Path(str(db_path) + suffix)
        if path.exists():
            total += path.stat().st_size
    return total


def _tree_bytes(directory: pathlib.Path) -> int:
    """Return the total size of every file under a directory."""
    return sum(f.stat().st_size for f in directory.rglob("*") if f.is_file())


# ----------------------------------------------------------------------
# Phases
# ----------------------------------------------------------------------


def _warmup(root: pathlib.Path, file_size: int, dim: int) -> None:
    """Exercise the whole write path once on a throwaway library.

    Without this the first scale measured pays for interpreter warm-up, module
    imports, and a cold SQLite page cache, which makes it look slower than the
    larger scales that follow — the opposite of the trend being measured.
    """
    target = root / "warmup"
    scratch = target / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    rng = random.Random(0)

    db = _open_db(target)
    try:
        _, ids = _bench_insert(db, scratch, 25, file_size, rng)
        _bench_enrich(db, ids, dim, rng)
        _bench_search(db, dim, 1, 10, rng)
        _bench_indexed_reads(db, 2)
    finally:
        db.close()
    shutil.rmtree(target, ignore_errors=True)


def _bench_insert(
    db: SpectatorDB,
    scratch: pathlib.Path,
    count: int,
    file_size: int,
    rng: random.Random,
) -> tuple[Timings, list[str]]:
    """Insert ``count`` synthetic files, timing each insert individually.

    The source file is rewritten with fresh random bytes before every insert
    so that each record gets a distinct content hash, and so that the SHA-256
    is computed over data the OS has not already deduplicated. That write
    happens outside the timed region.
    """
    source = scratch / "source.jpg"
    base = datetime.now(timezone.utc)
    samples: list[float] = []
    ids: list[str] = []

    for index in range(count):
        source.write_bytes(rng.randbytes(file_size))
        captured_at = base - timedelta(seconds=index)
        device_id = _DEVICES[index % len(_DEVICES)]
        labels = [_LABELS[index % len(_LABELS)]] if index % 4 == 0 else []

        started = time.perf_counter()
        record_id = db.insert(
            source,
            MediaType.IMAGE,
            captured_at,
            device_id=device_id,
            labels=labels,
        )
        samples.append(time.perf_counter() - started)

        if record_id is not None:
            ids.append(record_id)

    source.unlink(missing_ok=True)
    return _summarize(samples), ids


def _bench_enrich(
    db: SpectatorDB,
    ids: list[str],
    dim: int,
    rng: random.Random,
) -> Timings:
    """Attach an embedding to every record, timing each update."""
    samples: list[float] = []
    for record_id in ids:
        vector = _unit_vector(dim, rng)
        started = time.perf_counter()
        db.update_enrichment(
            record_id,
            embedding=vector,
            embedding_model=EMBEDDING_MODEL,
        )
        samples.append(time.perf_counter() - started)
    return _summarize(samples)


def _bench_search(
    db: SpectatorDB,
    dim: int,
    repeats: int,
    limit: int,
    rng: random.Random,
) -> Timings:
    """Time repeated brute-force similarity searches with fresh query vectors."""
    db.search_similar(_unit_vector(dim, rng), model=EMBEDDING_MODEL, limit=limit)

    samples: list[float] = []
    for _ in range(repeats):
        query = _unit_vector(dim, rng)
        started = time.perf_counter()
        db.search_similar(query, model=EMBEDDING_MODEL, limit=limit)
        samples.append(time.perf_counter() - started)
    return _summarize(samples)


def _bench_indexed_reads(
    db: SpectatorDB,
    repeats: int,
) -> tuple[Timings, Timings, Timings]:
    """Time the ordinary gallery reads: two paged queries and a filtered count.

    The two query variants are measured separately on purpose. A bare
    time-range page walks ``idx_media_captured_at`` and stops at the limit.
    Adding a low-selectivity ``media_type`` filter makes SQLite prefer
    ``idx_media_media_type``, which matches nearly every row and forces a temp
    B-tree sort of the whole match set before ``LIMIT`` applies — so the second
    number grows with the library while the first does not. Reporting only one
    of them would misrepresent how paging behaves.
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=1)

    db.query(start=start, end=end, limit=50)
    db.count(media_type=MediaType.IMAGE)

    range_samples: list[float] = []
    filtered_samples: list[float] = []
    count_samples: list[float] = []
    for _ in range(repeats):
        began = time.perf_counter()
        db.query(start=start, end=end, limit=50)
        range_samples.append(time.perf_counter() - began)

        began = time.perf_counter()
        db.query(start=start, end=end, media_type=MediaType.IMAGE, limit=50)
        filtered_samples.append(time.perf_counter() - began)

        began = time.perf_counter()
        db.count(media_type=MediaType.IMAGE, labels=["person"])
        count_samples.append(time.perf_counter() - began)

    return (
        _summarize(range_samples),
        _summarize(filtered_samples),
        _summarize(count_samples),
    )


# ----------------------------------------------------------------------
# Scale run
# ----------------------------------------------------------------------


@dataclass
class ScaleResult:
    """Every measurement taken at a single library size."""

    records: int
    file_size: int
    dim: int
    insert: Timings
    enrich: Timings
    search: Timings
    query_range: Timings
    query_filtered: Timings
    count: Timings
    catalog_bytes_no_vectors: int
    catalog_bytes_with_vectors: int
    media_bytes: int


def _run_scale(
    root: pathlib.Path,
    records: int,
    file_size: int,
    dim: int,
    repeats: int,
    seed: int,
) -> ScaleResult:
    """Build a library of the given size and measure it end to end."""
    rng = random.Random(seed)
    root.mkdir(parents=True, exist_ok=True)
    scratch = root / "scratch"
    scratch.mkdir(exist_ok=True)

    db = _open_db(root)
    try:
        print(f"  inserting {records:,} records ...", flush=True)
        insert_timings, ids = _bench_insert(db, scratch, records, file_size, rng)

        catalog_before = _catalog_bytes(root / "catalog.db")
        media_bytes = _tree_bytes(root / "media")

        print(f"  attaching {len(ids):,} embeddings ({dim}-d) ...", flush=True)
        enrich_timings = _bench_enrich(db, ids, dim, rng)
        catalog_after = _catalog_bytes(root / "catalog.db")

        print(f"  searching ({repeats} queries) ...", flush=True)
        search_timings = _bench_search(db, dim, repeats, limit=10, rng=rng)

        print("  indexed reads ...", flush=True)
        range_timings, filtered_timings, count_timings = _bench_indexed_reads(
            db, max(repeats, 20)
        )
    finally:
        db.close()
        shutil.rmtree(scratch, ignore_errors=True)

    return ScaleResult(
        records=records,
        file_size=file_size,
        dim=dim,
        insert=insert_timings,
        enrich=enrich_timings,
        search=search_timings,
        query_range=range_timings,
        query_filtered=filtered_timings,
        count=count_timings,
        catalog_bytes_no_vectors=catalog_before,
        catalog_bytes_with_vectors=catalog_after,
        media_bytes=media_bytes,
    )


def _run_file_size_sweep(
    root: pathlib.Path,
    sizes: tuple[int, ...],
    records: int,
    seed: int,
) -> list[tuple[int, Timings]]:
    """Measure insert cost against file size at a fixed, small record count.

    Insert time is dominated by hashing and copying bytes, so this is the
    bridge from the synthetic file size used above to real photos and video
    without writing tens of gigabytes.
    """
    results: list[tuple[int, Timings]] = []
    for size in sizes:
        target = root / f"sweep-{size}"
        target.mkdir(parents=True, exist_ok=True)
        scratch = target / "scratch"
        scratch.mkdir(exist_ok=True)

        db = _open_db(target)
        try:
            print(f"  file size {_human_bytes(size)} ...", flush=True)
            timings, _ = _bench_insert(db, scratch, records, size, random.Random(seed))
        finally:
            db.close()
        results.append((size, timings))
        shutil.rmtree(target, ignore_errors=True)
    return results


# ----------------------------------------------------------------------
# Environment and reporting
# ----------------------------------------------------------------------


def _hardware_model() -> str:
    """Return a board or machine model string when the OS exposes one.

    Raspberry Pi OS publishes the board name in the device tree, which is
    what makes a Pi result identifiable rather than just "aarch64".
    """
    device_tree = pathlib.Path("/proc/device-tree/model")
    try:
        if device_tree.exists():
            return device_tree.read_bytes().decode("utf-8", "replace").strip("\x00 \n")
    except OSError:
        pass

    cpuinfo = pathlib.Path("/proc/cpuinfo")
    try:
        if cpuinfo.exists():
            for line in cpuinfo.read_text(errors="replace").splitlines():
                if line.startswith(("Model", "model name")):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return ""


def _environment() -> dict[str, str]:
    """Collect the machine details a reader needs to interpret the numbers."""
    return {
        "hardware": _hardware_model() or platform.processor() or "unknown",
        "system": f"{platform.system()} {platform.release()}",
        "machine": platform.machine(),
        "cpu_count": str(os.cpu_count() or 0),
        "python": f"{platform.python_implementation()} {platform.python_version()}",
        "sqlite": sqlite3.sqlite_version,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _human_bytes(size: float) -> str:
    """Format a byte count with a binary unit suffix."""
    for unit in ("B", "KiB", "MiB", "GiB"):
        if abs(size) < 1024.0 or unit == "GiB":
            precision = 0 if unit == "B" else 1
            return f"{size:.{precision}f} {unit}"
        size /= 1024.0
    return f"{size:.1f} GiB"


def _render(
    results: list[ScaleResult],
    sweep: list[tuple[int, Timings]],
    environment: dict[str, str],
) -> str:
    """Render every measurement as Markdown ready to paste into the article."""
    lines: list[str] = []
    add = lines.append

    add("## Environment")
    add("")
    add(f"- Hardware: {environment['hardware']}")
    add(
        f"- OS: {environment['system']} ({environment['machine']}, "
        f"{environment['cpu_count']} cores)"
    )
    add(f"- Python: {environment['python']}, SQLite {environment['sqlite']}")
    add(f"- Run: {environment['timestamp']}")
    add("")

    if results:
        file_size = _human_bytes(results[0].file_size)
        add(f"## Insert (`insert()`, {file_size} files)")
        add("")
        add("| records | median | p95 | max | inserts/sec | wall clock |")
        add("| ---: | ---: | ---: | ---: | ---: | ---: |")
        for result in results:
            timings = result.insert
            add(
                f"| {result.records:,} | {timings.median_ms:.2f} ms "
                f"| {timings.p95_ms:.2f} ms | {timings.max_ms:.2f} ms "
                f"| {timings.ops_per_s:,.0f} | {timings.total_s:.1f} s |"
            )
        add("")

        add("## Similarity search (`search_similar()`, brute force)")
        add("")
        add("| vectors | dim | median | p95 | max |")
        add("| ---: | ---: | ---: | ---: | ---: |")
        for result in results:
            timings = result.search
            add(
                f"| {result.records:,} | {result.dim} "
                f"| {timings.median_ms:.1f} ms | {timings.p95_ms:.1f} ms "
                f"| {timings.max_ms:.1f} ms |"
            )
        add("")

        add("## Reads and updates")
        add("")
        add(
            "| records | `query()` time range | `query()` + media_type | "
            "`count()` by label | `update_enrichment()` |"
        )
        add("| ---: | ---: | ---: | ---: | ---: |")
        for result in results:
            add(
                f"| {result.records:,} "
                f"| {result.query_range.median_ms:.2f} ms "
                f"| {result.query_filtered.median_ms:.2f} ms "
                f"| {result.count.median_ms:.2f} ms "
                f"| {result.enrich.median_ms:.2f} ms |"
            )
        add("")
        add(
            "Both queries page 50 rows. The first is served by "
            "`idx_media_captured_at`; adding the `media_type` filter sends "
            "SQLite to `idx_media_media_type` instead, which matches nearly "
            "every row and sorts the whole match set before applying `LIMIT`."
        )
        add("")

        add("## On-disk size")
        add("")
        add(
            "| records | catalog, no vectors | catalog, with vectors | "
            "bytes/record | media files |"
        )
        add("| ---: | ---: | ---: | ---: | ---: |")
        for result in results:
            per_record = (
                result.catalog_bytes_with_vectors / result.records
                if result.records
                else 0
            )
            add(
                f"| {result.records:,} "
                f"| {_human_bytes(result.catalog_bytes_no_vectors)} "
                f"| {_human_bytes(result.catalog_bytes_with_vectors)} "
                f"| {per_record:,.0f} B "
                f"| {_human_bytes(result.media_bytes)} |"
            )
        add("")

    if sweep:
        add(f"## Insert cost by file size ({sweep[0][1].count} inserts each)")
        add("")
        add("| file size | median | p95 | inserts/sec | MiB/sec |")
        add("| ---: | ---: | ---: | ---: | ---: |")
        for size, timings in sweep:
            throughput = (
                (size * timings.ops_per_s) / (1024 * 1024) if timings.ops_per_s else 0.0
            )
            add(
                f"| {_human_bytes(size)} | {timings.median_ms:.2f} ms "
                f"| {timings.p95_ms:.2f} ms | {timings.ops_per_s:,.0f} "
                f"| {throughput:,.1f} |"
            )
        add("")

    return "\n".join(lines)


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------


def _parse_scales(raw: str) -> tuple[int, ...]:
    """Parse a comma-separated list of record counts."""
    try:
        scales = tuple(int(part) for part in raw.split(",") if part.strip())
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid scale list: {raw!r}") from None
    if not scales or any(scale <= 0 for scale in scales):
        raise argparse.ArgumentTypeError("scales must be positive integers")
    return scales


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        description="Benchmark spectator-db insert, search, and storage size.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--scales",
        type=_parse_scales,
        default=_DEFAULT_SCALES,
        help="comma-separated record counts (default: 1000,10000,50000)",
    )
    parser.add_argument(
        "--dim",
        type=int,
        default=64,
        help="embedding dimension (default: 64, matching examples/photos.py)",
    )
    parser.add_argument(
        "--file-size",
        type=int,
        default=8192,
        help="synthetic media file size in bytes (default: 8192)",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=5,
        help="similarity searches timed per scale (default: 5)",
    )
    parser.add_argument(
        "--file-size-sweep",
        action="store_true",
        help="also measure how insert cost scales with file size",
    )
    parser.add_argument(
        "--sweep-records",
        type=int,
        default=200,
        help="inserts per file size in the sweep (default: 200)",
    )
    parser.add_argument(
        "--workdir",
        type=pathlib.Path,
        default=None,
        help="where to build the corpora (default: a temporary directory)",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="keep the generated corpora instead of deleting them",
    )
    parser.add_argument(
        "--json",
        type=pathlib.Path,
        default=None,
        help="also write the raw measurements to this JSON file",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20260820,
        help="seed for reproducible corpora (default: 20260820)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the benchmark suite and print a Markdown report."""
    args = _build_parser().parse_args(argv)

    if args.dim <= 0:
        print("--dim must be positive", file=sys.stderr)
        return 2
    if args.file_size <= 0:
        print("--file-size must be positive", file=sys.stderr)
        return 2
    if args.repeats <= 0:
        print("--repeats must be positive", file=sys.stderr)
        return 2

    owns_workdir = args.workdir is None
    workdir = (
        pathlib.Path(tempfile.mkdtemp(prefix="spectatordb-bench-"))
        if owns_workdir
        else args.workdir
    )
    workdir.mkdir(parents=True, exist_ok=True)

    largest = max(args.scales)
    projected = largest * args.file_size
    print(f"Working directory: {workdir}", flush=True)
    print(
        f"Largest scale writes about {_human_bytes(projected)} of media files.",
        flush=True,
    )

    results: list[ScaleResult] = []
    sweep: list[tuple[int, Timings]] = []
    try:
        print("Warming up ...", flush=True)
        _warmup(workdir, args.file_size, args.dim)

        for scale in args.scales:
            print(f"\nScale {scale:,}", flush=True)
            results.append(
                _run_scale(
                    workdir / f"scale-{scale}",
                    records=scale,
                    file_size=args.file_size,
                    dim=args.dim,
                    repeats=args.repeats,
                    seed=args.seed,
                )
            )
            if not args.keep:
                shutil.rmtree(workdir / f"scale-{scale}", ignore_errors=True)

        if args.file_size_sweep:
            print("\nFile-size sweep", flush=True)
            sweep = _run_file_size_sweep(
                workdir,
                sizes=(8 * 1024, 256 * 1024, 2 * 1024 * 1024),
                records=args.sweep_records,
                seed=args.seed,
            )
    finally:
        if owns_workdir and not args.keep:
            shutil.rmtree(workdir, ignore_errors=True)

    environment = _environment()
    report = _render(results, sweep, environment)
    print("\n" + report)

    if args.json is not None:
        payload = {
            "environment": environment,
            "scales": [asdict(result) for result in results],
            "file_size_sweep": [
                {"file_size": size, "timings": asdict(timings)}
                for size, timings in sweep
            ],
        }
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, indent=2) + "\n")
        print(f"Raw measurements written to {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
