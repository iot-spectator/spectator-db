# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Starting with 0.2.0, the public API exported from the `spectatordb` package root
is covered by semantic versioning.

## [Unreleased]

### Added
- `benchmarks/benchmark.py` — a stdlib-only harness measuring insert
  throughput, similarity-search latency, and on-disk size at 1k/10k/50k
  records, with a file-size sweep and a Markdown/JSON report. Runs unmodified
  on a laptop and a Raspberry Pi. Methodology and recorded runs are in
  `benchmarks/README.md`.

### Documented
- Two scaling limits the benchmarks surfaced, now written down in
  `benchmarks/README.md`: `query()` with a low-selectivity `media_type` filter
  is not index-served (SQLite sorts the whole match set before `LIMIT`), and
  `count()` filtered by label always scans because labels are matched through
  `json_each`.

## [0.2.0] - 2026-08-05

First release aimed at real personal use: point it at a folder of photos and
videos and search them, fully offline with a stdlib-only core.

> **Note on 0.1.0.** A `0.1.0` build was published to PyPI on 2026-06-13 from an
> earlier state of the tree, before the work described below landed. That
> release is superseded and does not contain any of these changes. Because PyPI
> version numbers can never be reused, this release is numbered `0.2.0`; the
> version bump reflects the collision, not a second round of API changes.

### Added
- `SpectatorDB.import_dir()` — bulk-import every recognized image/video under a
  directory (recursive by default), skipping duplicates.
- Optional `captured_at` on `insert()` — when omitted, the capture time is read
  from the image's EXIF `DateTimeOriginal`, falling back to the file's mtime.
- Zero-dependency EXIF reader (`spectatordb.exif.read_captured_at`) for JPEG/TIFF
  `DateTimeOriginal`. Optional `[exif]` extra adds Pillow for richer formats
  (e.g. HEIC); the core never imports Pillow.
- Content-hash deduplication: `insert()` now computes a SHA-256 `content_hash`
  when not supplied, accepts `skip_duplicates=True`, and there is a new
  `exists(content_hash)` check.
- `count(...)` — count records matching the same filters as `query()`, for
  paging without materializing rows.
- `update_metadata(...)` — correct intrinsic fields (`captured_at`, `device_id`,
  `duration`) after the fact, complementing `update_enrichment`.
- Test asserting the package opens no network sockets during a full workflow.
- `examples/photos.py` — a complete personal photo-library CLI built on the
  public API: folder import, tagging, search by time/type/label/device,
  similarity search, export, and maintenance. Stdlib-only except `embed`,
  which uses the `[exif]` extra's decoder to compute a color-layout signature.

### Changed
- **Lowered the required Python from 3.13 to 3.11** so it runs on Raspberry Pi
  OS (Bookworm). Dropped the advisory `@override` decorators; `StrEnum` and
  `Self` remain available on 3.11.
- `insert()` now returns `str | None` (`None` when skipped as a duplicate).
- Declared `[project.optional-dependencies]` with the `exif` extra; the core
  still installs with zero runtime dependencies.
- Metadata schema bumped to version 2, adding an index on `content_hash`
  (forward-migrated automatically for existing databases).
- `search_similar` precomputes the query vector's norm once instead of per
  candidate — same results, less work per brute-force scan.

[Unreleased]: https://github.com/iot-spectator/spectator-db/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/iot-spectator/spectator-db/releases/tag/v0.2.0
