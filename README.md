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
