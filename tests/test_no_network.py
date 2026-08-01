"""Guard test: spectator-db must never touch the network.

Offline-always is a core guarantee. This test blocks socket creation and then
exercises a full workflow; if any operation tries to open a socket, it fails.
"""

import socket

from datetime import datetime, timezone

import pytest

from spectatordb import (
    LocalStorage,
    MediaType,
    SQLiteMetadataStore,
    SpectatorDB,
)


@pytest.fixture
def no_network(monkeypatch):
    """Make any attempt to create a socket raise immediately."""

    def _blocked(*args, **kwargs):
        raise AssertionError("spectator-db attempted to open a network socket")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


def test_full_workflow_opens_no_sockets(no_network, tmp_path):
    db = SpectatorDB(
        storage=LocalStorage(storage_dir=tmp_path / "media"),
        metadata_store=SQLiteMetadataStore(db_path=tmp_path / "spectator.db"),
    )

    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"\xff\xd8\xff\xe0" + b"payload")

    record_id = db.insert(
        photo,
        MediaType.IMAGE,
        captured_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    assert record_id is not None

    db.update_enrichment(
        record_id, labels=["cat"], embedding=[0.1, 0.2], embedding_model="m"
    )
    db.update_metadata(record_id, device_id="pi-01")
    db.query()
    db.count()
    db.search_similar([0.1, 0.2], model="m")
    db.exists("0" * 64)
    db.get(record_id)
    db.retrieve(record_id, tmp_path / "out.jpg")
    db.reconcile()
    db.delete(record_id)
    db.close()
