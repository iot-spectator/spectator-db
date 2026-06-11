import pathlib
import pytest

from datetime import datetime, timezone

from spectatordb.metadata.sqlite_metadata_store import SQLiteMetadataStore
from spectatordb.models import MediaType, UNSET
from spectatordb.spectatordb import SpectatorDB
from spectatordb.storage.local_storage import LocalStorage


@pytest.fixture
def db(tmp_path):
    storage = LocalStorage(storage_dir=tmp_path / "media")
    metadata_store = SQLiteMetadataStore(db_path=tmp_path / "spectator.db")
    return SpectatorDB(storage=storage, metadata_store=metadata_store)


@pytest.fixture
def sample_image(tmp_path):
    path = tmp_path / "photo.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    return path


@pytest.fixture
def sample_video(tmp_path):
    path = tmp_path / "clip.avi"
    path.write_bytes(b"\x00" * 500)
    return path


class TestInsert:
    def test_insert_returns_id(self, db, sample_image):
        record_id = db.insert(
            sample_image,
            MediaType.IMAGE,
            captured_at=datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        )
        assert isinstance(record_id, str)
        assert len(record_id) > 0

    def test_insert_stores_file(self, db, sample_image, tmp_path):
        record_id = db.insert(
            sample_image,
            MediaType.IMAGE,
            captured_at=datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        )
        dest = tmp_path / "retrieved.jpg"
        db.retrieve(record_id, dest)
        assert dest.exists()
        assert dest.read_bytes() == sample_image.read_bytes()

    def test_insert_with_metadata(self, db, sample_video):
        record_id = db.insert(
            sample_video,
            MediaType.VIDEO,
            captured_at=datetime(2025, 6, 15, 14, 0, 0, tzinfo=timezone.utc),
            duration=10.5,
            device_id="pi-01",
            labels=["person", "car"],
            description="A person near a car",
        )
        record = db.get(record_id)
        assert record.media_type == MediaType.VIDEO
        assert record.duration == 10.5
        assert record.device_id == "pi-01"
        assert record.labels == ["person", "car"]
        assert record.description == "A person near a car"
        assert record.format == "avi"
        assert record.size == 500

    def test_insert_with_embedding(self, db, sample_image):
        record_id = db.insert(
            sample_image,
            MediaType.IMAGE,
            captured_at=datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
            embedding=[0.1, 0.2, 0.3],
            embedding_model="test-model",
        )
        record = db.get(record_id)
        assert record.embedding == [0.1, 0.2, 0.3]
        assert record.embedding_model == "test-model"
        assert record.embedding_dim == 3

    def test_insert_atomicity_no_orphan_on_failure(self, tmp_path, sample_image):
        storage = LocalStorage(storage_dir=tmp_path / "media")
        # Use a bad db path to force metadata insert failure
        metadata_store = SQLiteMetadataStore(db_path=tmp_path / "spectator.db")
        db = SpectatorDB(storage=storage, metadata_store=metadata_store)
        metadata_store.close()

        with pytest.raises(Exception):
            db.insert(
                sample_image,
                MediaType.IMAGE,
                captured_at=datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
            )

        stored = list((tmp_path / "media").iterdir())
        assert stored == [], "No orphaned file should remain after a failed insert"


class TestGet:
    def test_get_returns_record(self, db, sample_image):
        record_id = db.insert(
            sample_image,
            MediaType.IMAGE,
            captured_at=datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        )
        record = db.get(record_id)
        assert record.id == record_id
        assert record.media_type == MediaType.IMAGE
        assert record.inserted_at is not None

    def test_get_missing_raises(self, db):
        with pytest.raises(KeyError):
            db.get("nonexistent-id")


class TestDelete:
    def test_delete_removes_record_and_file(self, db, sample_image, tmp_path):
        record_id = db.insert(
            sample_image,
            MediaType.IMAGE,
            captured_at=datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        )
        db.delete(record_id)
        with pytest.raises(KeyError):
            db.get(record_id)
        dest = tmp_path / "should_not_exist.jpg"
        with pytest.raises(KeyError):
            db.retrieve(record_id, dest)

    def test_delete_missing_raises(self, db):
        with pytest.raises(KeyError):
            db.delete("nonexistent-id")


class TestRetrieve:
    def test_retrieve_copies_file(self, db, sample_image, tmp_path):
        record_id = db.insert(
            sample_image,
            MediaType.IMAGE,
            captured_at=datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        )
        dest = tmp_path / "output.jpg"
        db.retrieve(record_id, dest)
        assert dest.exists()
        assert dest.read_bytes() == sample_image.read_bytes()

    def test_retrieve_missing_raises(self, db):
        with pytest.raises(KeyError):
            db.retrieve("nonexistent-id", pathlib.Path("/tmp/out.jpg"))


class TestQuery:
    def test_query_returns_all(self, db, sample_image):
        db.insert(
            sample_image,
            MediaType.IMAGE,
            captured_at=datetime(2025, 6, 15, 10, 0, 0, tzinfo=timezone.utc),
        )
        db.insert(
            sample_image,
            MediaType.IMAGE,
            captured_at=datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        )
        results = db.query()
        assert len(results) == 2

    def test_query_filters_by_media_type(self, db, sample_image, sample_video):
        db.insert(
            sample_image,
            MediaType.IMAGE,
            captured_at=datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        )
        db.insert(
            sample_video,
            MediaType.VIDEO,
            captured_at=datetime(2025, 6, 15, 14, 0, 0, tzinfo=timezone.utc),
            duration=5.0,
        )
        results = db.query(media_type=MediaType.VIDEO)
        assert len(results) == 1
        assert results[0].media_type == MediaType.VIDEO

    def test_query_filters_by_time_range(self, db, sample_image):
        db.insert(
            sample_image,
            MediaType.IMAGE,
            captured_at=datetime(2025, 6, 15, 8, 0, 0, tzinfo=timezone.utc),
        )
        id2 = db.insert(
            sample_image,
            MediaType.IMAGE,
            captured_at=datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        )
        db.insert(
            sample_image,
            MediaType.IMAGE,
            captured_at=datetime(2025, 6, 15, 18, 0, 0, tzinfo=timezone.utc),
        )
        results = db.query(
            start=datetime(2025, 6, 15, 10, 0, 0, tzinfo=timezone.utc),
            end=datetime(2025, 6, 15, 15, 0, 0, tzinfo=timezone.utc),
        )
        assert len(results) == 1
        assert results[0].id == id2

    def test_query_filters_by_labels(self, db, sample_image):
        id1 = db.insert(
            sample_image,
            MediaType.IMAGE,
            captured_at=datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
            labels=["person"],
        )
        db.insert(
            sample_image,
            MediaType.IMAGE,
            captured_at=datetime(2025, 6, 15, 14, 0, 0, tzinfo=timezone.utc),
            labels=["car"],
        )
        results = db.query(labels=["person"])
        assert len(results) == 1
        assert results[0].id == id1


class TestUpdateEnrichment:
    def test_update_labels_and_description(self, db, sample_image):
        record_id = db.insert(
            sample_image,
            MediaType.IMAGE,
            captured_at=datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        )
        db.update_enrichment(
            record_id, labels=["bird"], description="A bird on a branch"
        )
        record = db.get(record_id)
        assert record.labels == ["bird"]
        assert record.description == "A bird on a branch"

    def test_update_embedding(self, db, sample_image):
        record_id = db.insert(
            sample_image,
            MediaType.IMAGE,
            captured_at=datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        )
        db.update_enrichment(
            record_id,
            embedding=[0.9, 0.1],
            embedding_model="clip-vit-b32",
        )
        record = db.get(record_id)
        assert record.embedding == [0.9, 0.1]
        assert record.embedding_model == "clip-vit-b32"
        assert record.embedding_dim == 2

    def test_update_missing_raises(self, db):
        with pytest.raises(KeyError):
            db.update_enrichment("nonexistent", labels=["x"])

    def test_unset_fields_unchanged(self, db, sample_image):
        record_id = db.insert(
            sample_image,
            MediaType.IMAGE,
            captured_at=datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
            labels=["original"],
        )
        db.update_enrichment(record_id, description="new description")
        record = db.get(record_id)
        assert record.labels == ["original"]
        assert record.description == "new description"


class TestSearchSimilar:
    def test_search_similar(self, db, sample_image):
        id1 = db.insert(
            sample_image,
            MediaType.IMAGE,
            captured_at=datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
            embedding=[1.0, 0.0, 0.0],
            embedding_model="test-model",
        )
        db.insert(
            sample_image,
            MediaType.IMAGE,
            captured_at=datetime(2025, 6, 15, 13, 0, 0, tzinfo=timezone.utc),
            embedding=[0.0, 1.0, 0.0],
            embedding_model="test-model",
        )
        results = db.search_similar([1.0, 0.0, 0.0], model="test-model")
        assert len(results) == 2
        assert results[0].id == id1


class TestReconcile:
    def test_reconcile_clean_db(self, db, sample_image):
        db.insert(
            sample_image,
            MediaType.IMAGE,
            captured_at=datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        )
        report = db.reconcile()
        assert report.orphaned_files == []
        assert report.dangling_rows == []
        assert report.deleted_files == 0
        assert report.deleted_rows == 0

    def test_reconcile_removes_orphaned_file(self, tmp_path, sample_image):
        storage_dir = tmp_path / "media"
        storage = LocalStorage(storage_dir=storage_dir)
        metadata_store = SQLiteMetadataStore(db_path=tmp_path / "spectator.db")
        db = SpectatorDB(storage=storage, metadata_store=metadata_store)

        # Plant an orphan file directly in storage (no metadata row)
        orphan = storage_dir / "orphan-file.jpg"
        orphan.write_bytes(b"\x00" * 10)

        report = db.reconcile()
        assert "orphan-file.jpg" in report.orphaned_files
        assert report.deleted_files == 1
        assert not orphan.exists()

    def test_reconcile_removes_dangling_row(self, tmp_path, sample_image):
        storage_dir = tmp_path / "media"
        storage = LocalStorage(storage_dir=storage_dir)
        metadata_store = SQLiteMetadataStore(db_path=tmp_path / "spectator.db")
        db = SpectatorDB(storage=storage, metadata_store=metadata_store)

        record_id = db.insert(
            sample_image,
            MediaType.IMAGE,
            captured_at=datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        )
        # Remove the file directly, leaving a dangling row
        record = db.get(record_id)
        (storage_dir / f"{record.id}.{record.format}").unlink()

        report = db.reconcile()
        assert record_id in report.dangling_rows
        assert report.deleted_rows == 1
        with pytest.raises(KeyError):
            db.get(record_id)
