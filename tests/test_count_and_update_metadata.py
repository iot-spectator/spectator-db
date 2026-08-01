"""Tests for count() and update_metadata()."""

from datetime import datetime, timezone

import pytest

from spectatordb.metadata.sqlite_metadata_store import SQLiteMetadataStore
from spectatordb.models import MediaType
from spectatordb.spectatordb import SpectatorDB
from spectatordb.storage.local_storage import LocalStorage


@pytest.fixture
def db(tmp_path):
    storage = LocalStorage(storage_dir=tmp_path / "media")
    metadata_store = SQLiteMetadataStore(db_path=tmp_path / "spectator.db")
    return SpectatorDB(storage=storage, metadata_store=metadata_store)


def _image(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"\xff\xd8\xff\xe0" + name.encode())
    return path


class TestCount:
    def test_counts_all(self, db, tmp_path):
        db.insert(_image(tmp_path, "a.jpg"), MediaType.IMAGE)
        db.insert(_image(tmp_path, "b.jpg"), MediaType.IMAGE)
        assert db.count() == 2

    def test_count_matches_query_with_filters(self, db, tmp_path):
        db.insert(
            _image(tmp_path, "a.jpg"),
            MediaType.IMAGE,
            captured_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            labels=["cat"],
        )
        db.insert(
            _image(tmp_path, "b.jpg"),
            MediaType.IMAGE,
            captured_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
            labels=["dog"],
        )
        assert db.count(labels=["cat"]) == 1
        assert db.count(labels=["cat"]) == len(db.query(labels=["cat"]))

    def test_count_by_media_type(self, db, tmp_path):
        db.insert(_image(tmp_path, "a.jpg"), MediaType.IMAGE)
        vid = tmp_path / "v.mp4"
        vid.write_bytes(b"\x00vid")
        db.insert(vid, MediaType.VIDEO)
        assert db.count(media_type=MediaType.IMAGE) == 1
        assert db.count(media_type=MediaType.VIDEO) == 1


class TestUpdateMetadata:
    def test_fixes_captured_at(self, db, tmp_path):
        record_id = db.insert(
            _image(tmp_path, "a.jpg"),
            MediaType.IMAGE,
            captured_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
        )
        corrected = datetime(2023, 5, 6, 7, 8, 9, tzinfo=timezone.utc)
        db.update_metadata(record_id, captured_at=corrected)
        assert db.get(record_id).captured_at == corrected

    def test_updates_device_and_duration(self, db, tmp_path):
        record_id = db.insert(_image(tmp_path, "a.jpg"), MediaType.IMAGE)
        db.update_metadata(record_id, device_id="pi-09", duration=3.5)
        record = db.get(record_id)
        assert record.device_id == "pi-09"
        assert record.duration == 3.5

    def test_clear_device_id(self, db, tmp_path):
        record_id = db.insert(
            _image(tmp_path, "a.jpg"), MediaType.IMAGE, device_id="pi-01"
        )
        db.update_metadata(record_id, device_id=None)
        assert db.get(record_id).device_id is None

    def test_unset_fields_unchanged(self, db, tmp_path):
        record_id = db.insert(
            _image(tmp_path, "a.jpg"), MediaType.IMAGE, device_id="pi-01"
        )
        db.update_metadata(record_id, duration=1.0)
        assert db.get(record_id).device_id == "pi-01"

    def test_missing_raises(self, db):
        with pytest.raises(KeyError):
            db.update_metadata("nonexistent", captured_at=datetime.now(timezone.utc))
