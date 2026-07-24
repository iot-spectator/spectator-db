"""Guards the curated public API and the documented README quick-start flow.

These tests import only from the ``spectatordb`` package root (the supported,
semver-protected surface) and exercise the exact flow shown in the README so the
documentation cannot silently drift from working code.
"""

import pathlib

from datetime import datetime, timezone

import pytest

import spectatordb


def test_public_api_exports() -> None:
    """Every name promised in __all__ is importable from the package root."""
    expected = {
        "SpectatorDB",
        "MediaRecord",
        "MediaType",
        "ReconcileReport",
        "UNSET",
        "Storage",
        "LocalStorage",
        "SaveMode",
        "MetadataStore",
        "SQLiteMetadataStore",
    }
    assert expected <= set(spectatordb.__all__)
    for name in expected:
        assert hasattr(spectatordb, name), f"{name} missing from spectatordb"


def test_readme_quick_start(tmp_path: pathlib.Path) -> None:
    """The README quick-start flow runs end to end via the public API."""
    from spectatordb import (
        SpectatorDB,
        MediaType,
        LocalStorage,
        SQLiteMetadataStore,
    )

    db = SpectatorDB(
        storage=LocalStorage(tmp_path / "media"),
        metadata_store=SQLiteMetadataStore(tmp_path / "spectator.db"),
    )

    snapshot = tmp_path / "snapshot.jpg"
    snapshot.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg-bytes\xff\xd9")

    # 1. Store a capture.
    record_id = db.insert(
        snapshot,
        media_type=MediaType.IMAGE,
        captured_at=datetime.now(timezone.utc),
        device_id="pi-01",
        labels=["person"],
    )
    assert record_id is not None

    # 2. Enrich later.
    db.update_enrichment(
        record_id,
        description="A person at the front door",
        embedding=[0.10, 0.20, 0.30],
        embedding_model="clip-vit-b32",
    )

    # 3. Query with composable filters.
    hits = db.query(media_type=MediaType.IMAGE, labels=["person"], limit=10)
    assert len(hits) == 1
    assert hits[0].id == record_id
    assert hits[0].description == "A person at the front door"

    # 4. Semantic similarity search, scoped to one embedding model.
    similar = db.search_similar([0.11, 0.19, 0.31], model="clip-vit-b32", limit=5)
    assert len(similar) == 1
    assert similar[0].id == record_id

    # A different model shares no vector space, so it matches nothing.
    assert db.search_similar([0.11, 0.19, 0.31], model="other-model") == []

    # 5. Read a record and copy its file back out, byte-for-byte.
    record = db.get(record_id)
    assert record.device_id == "pi-01"
    out = tmp_path / "out.jpg"
    db.retrieve(record_id, out)
    assert out.read_bytes() == snapshot.read_bytes()


def test_retrieve_missing_file_raises(tmp_path: pathlib.Path) -> None:
    """A clear FileNotFoundError is raised for an unknown stored file."""
    storage = spectatordb.LocalStorage(tmp_path / "media")
    with pytest.raises(FileNotFoundError, match="File 'nope.jpg' not found"):
        storage.retrieve("nope.jpg", tmp_path / "dest.jpg")


def _store_with_embedding(
    tmp_path: pathlib.Path, embedding: list[float], model: str
) -> spectatordb.SpectatorDB:
    from spectatordb import SpectatorDB, MediaType, LocalStorage, SQLiteMetadataStore

    db = SpectatorDB(
        storage=LocalStorage(tmp_path / "media"),
        metadata_store=SQLiteMetadataStore(tmp_path / "spectator.db"),
    )
    media = tmp_path / "f.jpg"
    media.write_bytes(b"x")
    rid = db.insert(
        media, media_type=MediaType.IMAGE, captured_at=datetime.now(timezone.utc)
    )
    assert rid is not None
    db.update_enrichment(rid, embedding=embedding, embedding_model=model)
    return db


def test_search_similar_dimension_mismatch_raises(tmp_path: pathlib.Path) -> None:
    """A wrong-dimension query vector raises instead of silently truncating."""
    db = _store_with_embedding(tmp_path, [1.0, 0.0, 0.0, 0.0], "m1")
    with pytest.raises(ValueError, match="dimension"):
        db.search_similar([1.0, 0.0], model="m1")
    db.close()


def test_search_similar_matching_dimension_ok(tmp_path: pathlib.Path) -> None:
    """A correctly sized query vector still works after the dimension guard."""
    db = _store_with_embedding(tmp_path, [1.0, 0.0, 0.0, 0.0], "m1")
    results = db.search_similar([1.0, 0.0, 0.0, 0.0], model="m1")
    assert len(results) == 1
    db.close()


def test_context_manager_closes_backends(tmp_path: pathlib.Path) -> None:
    """SpectatorDB works as a context manager and closes the SQLite store."""
    from spectatordb import SpectatorDB, LocalStorage, SQLiteMetadataStore

    store = SQLiteMetadataStore(tmp_path / "spectator.db")
    with SpectatorDB(LocalStorage(tmp_path / "media"), store) as db:
        assert db.query() == []

    # The connection is closed on context exit; using it now raises.
    with pytest.raises(Exception):
        store._connection.execute("SELECT 1")
