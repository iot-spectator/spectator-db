# SpectatorDB

SpectatorDB is an embeddable, offline-first media-intelligence store for Python.
It keeps each media file **and** its structured metadata **and** its vector
embedding behind a single interface — the union that neither an object store nor
a vector database gives you alone — with **zero required runtime dependencies**
and no server to run.

It is designed for per-device autonomy on commodity hardware (e.g. a Raspberry
Pi): each device owns its own data and works with no cloud, no network, and no
AI model present. AI enrichment is optional and applied *after* a capture is
stored, so a slow or missing model never costs you data.

## Features

- **One store for media + metadata + embeddings**, backed by the local file
  system and SQLite.
- **One-line folder import** with EXIF/mtime capture times and SHA-256
  content-hash deduplication.
- **Composable queries** by time range, media type, device id, and labels
  (any-match), newest-first, with limit/offset, plus `count()` for paging.
- **Semantic similarity search** over embeddings, scoped to a single embedding
  model — pure-Python cosine, no extra dependencies.
- **Store-first, enrich-later**: insert immediately, attach labels/description/
  embedding afterward via `update_enrichment`.
- **Durable by design**: atomic insert/delete with compensating actions,
  `reconcile()` to sweep orphans, schema versioning with forward migrations, and
  UTC-normalized timestamps at the API boundary.
- **Pluggable backends** via the `Storage` and `MetadataStore` ABCs.

## Privacy & guarantees

- **Offline always.** No network calls, no telemetry — nothing ever leaves the
  device. A test in the suite asserts the package opens no sockets.
- **Zero required runtime dependencies.** The core is stdlib-only. The optional
  `[exif]` extra pulls in Pillow for richer photo formats; the core never
  imports it.
- **Two-folder portability.** Your data is just a folder of media files plus one
  SQLite catalog — open, inspectable, and readable decades from now.

## Requirements

- Python 3.11+ (runs on Raspberry Pi OS Bookworm)

## Installation

```bash
$ python -m pip install spectator-db            # zero-dependency core
$ python -m pip install "spectator-db[exif]"    # + Pillow for richer EXIF/HEIC
```

To work on the library itself, clone the repository and install it in editable
mode with the development tools:

```bash
$ git clone https://github.com/iot-spectator/spectator-db.git
$ cd spectator-db
$ python -m pip install -e .
$ python -m pip install -r requirements.txt  # dev/test/docs tools
```

## Quick start

```python
import pathlib
from datetime import datetime, timezone

from spectatordb import SpectatorDB, MediaType, LocalStorage, SQLiteMetadataStore

# Compose a store from a file-storage backend and a metadata backend.
db = SpectatorDB(
    storage=LocalStorage(pathlib.Path("./media")),
    metadata_store=SQLiteMetadataStore(pathlib.Path("./spectator.db")),
)

# 1. Import a whole folder in one line. Capture times come from EXIF (falling
#    back to file mtime), and duplicates are skipped by content hash.
ids = db.import_dir(pathlib.Path("~/Pictures").expanduser())

# 2. Or store a single capture. captured_at is optional — omit it and it is
#    read from EXIF, then the file's mtime. Returns None if skip_duplicates
#    skipped it.
record_id = db.insert(
    pathlib.Path("/path/to/snapshot.jpg"),
    media_type=MediaType.IMAGE,
    device_id="pi-01",
    labels=["person"],
    skip_duplicates=True,
)

# 3. Enrich later (store-first, enrich-later). embedding and embedding_model
#    must be set together.
db.update_enrichment(
    record_id,
    description="A person at the front door",
    embedding=[0.10, 0.20, 0.30],
    embedding_model="clip-vit-b32",
)

# 4. Query with composable filters, newest-first; count() pages without
#    loading rows.
hits = db.query(media_type=MediaType.IMAGE, labels=["person"], limit=10)
total = db.count(media_type=MediaType.IMAGE, labels=["person"])

# 5. Semantic similarity search, scoped to one embedding model.
similar = db.search_similar([0.11, 0.19, 0.31], model="clip-vit-b32", limit=5)

# 6. Fix a wrong capture time or device after the fact.
db.update_metadata(record_id, captured_at=datetime(2025, 6, 15, tzinfo=timezone.utc))

# 7. Read a record and copy its file back out.
record = db.get(record_id)
db.retrieve(record_id, pathlib.Path("./out.jpg"))
```

## Example: a personal photo library

[`examples/photos.py`](examples/photos.py) is a complete command-line tool built
on the public API — import a folder, tag it, search it, find look-alikes:

```bash
$ python examples/photos.py import ~/Pictures
imported 2153 file(s) from /home/you/Pictures
library now holds 2153 record(s)

$ python examples/photos.py list --type image --since 2026-01-01 --limit 3
7e281c56  2026-03-14 09:12  image     2.4 MB  -
1e457344  2026-02-02 17:40  image     1.9 MB  -
cd4f7678  2026-01-08 11:05  image     3.1 MB  -

$ python examples/photos.py tag 7e281c56 --add beach --add sunset
$ python examples/photos.py list --label beach
$ python examples/photos.py similar 7e281c56
```

Every command except `embed` runs on the stdlib-only core. `embed` needs an
image decoder, so it requires the `[exif]` extra:

```bash
$ python -m pip install "spectator-db[exif]"
$ python examples/photos.py embed
```

The embedding it computes is a 64-dimension color-layout signature — a 4x4 grid
of mean RGB plus a luma histogram. It matches on **color and composition, not
meaning**: it will find your other beach photos, but it does not understand what
a beach is. It exists so the similarity path is exercised end to end with no
dependencies to speak of. Swapping in a real model such as CLIP means replacing
one function; storage and search do not change.

## Public API

The supported, semver-protected surface is exported from the `spectatordb`
package root:

```python
from spectatordb import (
    SpectatorDB,         # the facade orchestrating storage + metadata
    MediaRecord,         # the stored-item data model
    MediaType,           # IMAGE | VIDEO
    ReconcileReport,     # result of SpectatorDB.reconcile()
    UNSET,               # sentinel for partial update_enrichment() updates
    Storage,             # file-storage backend ABC
    LocalStorage,        # local-filesystem Storage backend
    SaveMode,            # COPY | MOVE
    MetadataStore,       # metadata backend ABC
    SQLiteMetadataStore, # SQLite MetadataStore backend (default)
)
```

`SpectatorDB` methods: `insert`, `import_dir`, `exists`, `update_enrichment`,
`update_metadata`, `get`, `retrieve`, `query`, `count`, `search_similar`,
`delete`, `reconcile`.

## Concurrency

A `SQLiteMetadataStore` uses one WAL-mode connection per process and serializes
writes with a lock; reads are concurrent. It is thread-safe for the expected
low-write workload — use **one instance per process**.

## Performance

Measured, not estimated. [`benchmarks/`](benchmarks/) holds a stdlib-only
harness that runs unmodified on a laptop and a Raspberry Pi; the numbers below
are one laptop pass ([full report](benchmarks/results/laptop.md), methodology
and caveats in [`benchmarks/README.md`](benchmarks/README.md)).

| records | insert (median) | similarity search | paged `query()` | catalog size |
| ---: | ---: | ---: | ---: | ---: |
| 1,000 | 2.7 ms | 36 ms | 1.5 ms | 2.2 MiB |
| 10,000 | 1.8 ms | 411 ms | 1.6 ms | 22 MiB |
| 50,000 | 2.0 ms | 2.1 s | 1.8 ms | 110 MiB |

Read those honestly:

- **Inserts and paged queries stay flat** as the library grows. Import
  throughput is bound by the per-insert commit, so real multi-megabyte photos
  land at roughly 100 files/sec rather than the ~400/sec small files suggest.
- **Similarity search is brute force and O(N).** Every vector for the model is
  loaded, JSON-decoded, and scored on each call, and `limit` bounds the results
  rather than the work. It is comfortable at 1k, sluggish at 10k, and not
  interactive at 50k — on a Pi, sooner. Fixing that means an index, not a
  faster loop.
- **Vectors dominate the catalog**: ~468 B/record without an embedding,
  ~2.3 KiB with a 64-d one, because vectors are stored as JSON text.
- **`query()` filtered by `media_type` is not index-served** and grows with the
  library (39.9 ms at 50k against 1.8 ms unfiltered). See the benchmark README.

Run it yourself:

```bash
$ python benchmarks/benchmark.py --scales 1000,10000
```
