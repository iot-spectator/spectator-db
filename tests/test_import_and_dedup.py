"""Tests for captured_at fallback, content-hash dedup, and import_dir."""

import os

from datetime import datetime, timezone

import pytest

from spectatordb.metadata.sqlite_metadata_store import SQLiteMetadataStore
from spectatordb.models import MediaType
from spectatordb.spectatordb import SpectatorDB, _hash_file
from spectatordb.storage.local_storage import LocalStorage

from tests.test_exif import _build_exif_jpeg


@pytest.fixture
def db(tmp_path):
    storage = LocalStorage(storage_dir=tmp_path / "media")
    metadata_store = SQLiteMetadataStore(db_path=tmp_path / "spectator.db")
    return SpectatorDB(storage=storage, metadata_store=metadata_store)


class TestCapturedAtFallback:
    def test_falls_back_to_mtime(self, db, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"\x00" * 64)
        mtime = datetime(2022, 3, 4, 5, 6, 7, tzinfo=timezone.utc)
        os.utime(video, (mtime.timestamp(), mtime.timestamp()))

        record_id = db.insert(video, MediaType.VIDEO)
        assert db.get(record_id).captured_at == mtime

    def test_image_uses_exif(self, db, tmp_path):
        photo = tmp_path / "photo.jpg"
        photo.write_bytes(_build_exif_jpeg("2019:11:22 08:15:30"))

        record_id = db.insert(photo, MediaType.IMAGE)
        # EXIF has no timezone; the store normalizes the naive value to UTC.
        assert db.get(record_id).captured_at == datetime(
            2019, 11, 22, 8, 15, 30, tzinfo=timezone.utc
        )

    def test_image_without_exif_falls_back_to_mtime(self, db, tmp_path):
        photo = tmp_path / "plain.jpg"
        photo.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 32)
        mtime = datetime(2020, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        os.utime(photo, (mtime.timestamp(), mtime.timestamp()))

        record_id = db.insert(photo, MediaType.IMAGE)
        assert db.get(record_id).captured_at == mtime


class TestDedup:
    def test_content_hash_is_computed_and_stored(self, db, tmp_path):
        photo = tmp_path / "photo.jpg"
        photo.write_bytes(b"\xff\xd8\xff\xe0hello")
        record_id = db.insert(photo, MediaType.IMAGE)
        assert db.get(record_id).content_hash == _hash_file(photo)

    def test_exists_by_hash(self, db, tmp_path):
        photo = tmp_path / "photo.jpg"
        photo.write_bytes(b"\xff\xd8\xff\xe0hello")
        db.insert(photo, MediaType.IMAGE)
        assert db.exists(_hash_file(photo)) is True
        assert db.exists("0" * 64) is False

    def test_skip_duplicates_skips_second_insert(self, db, tmp_path):
        photo = tmp_path / "a.jpg"
        photo.write_bytes(b"\xff\xd8\xff\xe0identical")
        copy = tmp_path / "b.jpg"  # same bytes, different name
        copy.write_bytes(photo.read_bytes())

        first = db.insert(photo, MediaType.IMAGE, skip_duplicates=True)
        second = db.insert(copy, MediaType.IMAGE, skip_duplicates=True)
        assert first is not None
        assert second is None
        assert len(db.query()) == 1

    def test_without_skip_duplicates_both_inserted(self, db, tmp_path):
        photo = tmp_path / "a.jpg"
        photo.write_bytes(b"\xff\xd8\xff\xe0identical")
        assert db.insert(photo, MediaType.IMAGE) is not None
        assert db.insert(photo, MediaType.IMAGE) is not None
        assert len(db.query()) == 2


class TestImportDir:
    def _make_tree(self, root):
        root.mkdir(parents=True, exist_ok=True)
        (root / "one.jpg").write_bytes(b"\xff\xd8\xff\xe0one")
        (root / "two.png").write_bytes(b"\x89PNGtwo")
        (root / "clip.mp4").write_bytes(b"\x00mp4")
        (root / "notes.txt").write_bytes(b"ignore me")
        sub = root / "sub"
        sub.mkdir()
        (sub / "three.mov").write_bytes(b"\x00mov")

    def test_imports_recognized_media_recursively(self, db, tmp_path):
        root = tmp_path / "library"
        self._make_tree(root)

        ids = db.import_dir(root)
        assert len(ids) == 4  # jpg, png, mp4, mov — txt ignored
        assert len(db.query()) == 4

    def test_non_recursive_skips_subdirs(self, db, tmp_path):
        root = tmp_path / "library"
        self._make_tree(root)

        ids = db.import_dir(root, recursive=False)
        assert len(ids) == 3  # top-level jpg, png, mp4 only

    def test_import_dedups(self, db, tmp_path):
        root = tmp_path / "library"
        root.mkdir()
        (root / "a.jpg").write_bytes(b"\xff\xd8\xff\xe0same")
        (root / "b.jpg").write_bytes(b"\xff\xd8\xff\xe0same")

        ids = db.import_dir(root)
        assert len(ids) == 1

    def test_import_tags_device_id(self, db, tmp_path):
        root = tmp_path / "library"
        root.mkdir()
        (root / "a.jpg").write_bytes(b"\xff\xd8\xff\xe0a")

        ids = db.import_dir(root, device_id="pi-01")
        assert db.get(ids[0]).device_id == "pi-01"
