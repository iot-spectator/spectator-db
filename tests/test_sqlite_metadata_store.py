import sqlite3

import pytest

from datetime import datetime, timezone

from spectatordb.metadata.sqlite_metadata_store import SQLiteMetadataStore
from spectatordb.models import MediaRecord, MediaType, UNSET


@pytest.fixture
def store(tmp_path):
    return SQLiteMetadataStore(db_path=tmp_path / "test.db")


def _make_record(**overrides):
    defaults = dict(
        media_type=MediaType.IMAGE,
        captured_at=datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        format="jpg",
        size=1024,
    )
    defaults.update(overrides)
    return MediaRecord(**defaults)


class TestInsertAndGet:
    def test_insert_returns_id(self, store):
        record = _make_record()
        record_id = store.insert(record)
        assert record_id == record.id

    def test_get_returns_record(self, store):
        record = _make_record(device_id="pi-01", labels=["person", "car"])
        store.insert(record)
        result = store.get(record.id)
        assert result.id == record.id
        assert result.media_type == MediaType.IMAGE
        assert result.device_id == "pi-01"
        assert result.labels == ["person", "car"]
        assert result.format == "jpg"
        assert result.size == 1024
        assert result.inserted_at is not None

    def test_get_missing_raises(self, store):
        with pytest.raises(KeyError):
            store.get("nonexistent-id")

    def test_insert_with_all_fields(self, store):
        record = _make_record(
            media_type=MediaType.VIDEO,
            duration=10.5,
            device_id="pi-02",
            labels=["dog"],
            description="A dog running",
            embedding=[0.1, 0.2, 0.3],
            embedding_model="clip-vit-b32",
            embedding_dim=3,
        )
        store.insert(record)
        result = store.get(record.id)
        assert result.media_type == MediaType.VIDEO
        assert result.duration == 10.5
        assert result.description == "A dog running"
        assert result.embedding == [0.1, 0.2, 0.3]
        assert result.embedding_model == "clip-vit-b32"
        assert result.embedding_dim == 3

    def test_insert_normalizes_captured_at_to_utc(self, store):
        naive_dt = datetime(2025, 6, 15, 12, 0, 0)
        record = _make_record(captured_at=naive_dt)
        store.insert(record)
        result = store.get(record.id)
        assert result.captured_at.tzinfo is not None
        assert result.captured_at.tzinfo == timezone.utc


class TestDelete:
    def test_delete_removes_record(self, store):
        record = _make_record()
        store.insert(record)
        store.delete(record.id)
        with pytest.raises(KeyError):
            store.get(record.id)

    def test_delete_missing_raises(self, store):
        with pytest.raises(KeyError):
            store.delete("nonexistent-id")


class TestUpdateEnrichment:
    def test_update_labels(self, store):
        record = _make_record()
        store.insert(record)
        store.update_enrichment(record.id, labels=["cat", "dog"])
        result = store.get(record.id)
        assert result.labels == ["cat", "dog"]

    def test_update_description(self, store):
        record = _make_record()
        store.insert(record)
        store.update_enrichment(record.id, description="A cat on a mat")
        result = store.get(record.id)
        assert result.description == "A cat on a mat"

    def test_update_embedding(self, store):
        record = _make_record()
        store.insert(record)
        store.update_enrichment(
            record.id,
            embedding=[0.5, 0.6, 0.7],
            embedding_model="clip-vit-b32",
        )
        result = store.get(record.id)
        assert result.embedding == [0.5, 0.6, 0.7]
        assert result.embedding_model == "clip-vit-b32"
        assert result.embedding_dim == 3

    def test_clear_embedding(self, store):
        record = _make_record(
            embedding=[0.1, 0.2],
            embedding_model="test-model",
            embedding_dim=2,
        )
        store.insert(record)
        store.update_enrichment(record.id, embedding=None, embedding_model=None)
        result = store.get(record.id)
        assert result.embedding is None
        assert result.embedding_model is None
        assert result.embedding_dim is None

    def test_unset_fields_not_changed(self, store):
        record = _make_record(labels=["original"], description="keep me")
        store.insert(record)
        store.update_enrichment(record.id, labels=["updated"])
        result = store.get(record.id)
        assert result.labels == ["updated"]
        assert result.description == "keep me"

    def test_update_missing_raises(self, store):
        with pytest.raises(KeyError):
            store.update_enrichment("nonexistent-id", labels=["x"])

    def test_embedding_without_model_raises(self, store):
        record = _make_record()
        store.insert(record)
        with pytest.raises(ValueError):
            store.update_enrichment(record.id, embedding=[0.1, 0.2])

    def test_noop_update_on_missing_raises(self, store):
        with pytest.raises(KeyError):
            store.update_enrichment("nonexistent-id")


class TestQuery:
    def test_query_no_filters(self, store):
        r1 = _make_record(
            captured_at=datetime(2025, 6, 15, 10, 0, 0, tzinfo=timezone.utc)
        )
        r2 = _make_record(
            captured_at=datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        )
        store.insert(r1)
        store.insert(r2)
        results = store.query()
        assert len(results) == 2
        assert results[0].id == r2.id
        assert results[1].id == r1.id

    def test_query_by_time_range(self, store):
        r1 = _make_record(
            captured_at=datetime(2025, 6, 15, 8, 0, 0, tzinfo=timezone.utc)
        )
        r2 = _make_record(
            captured_at=datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        )
        r3 = _make_record(
            captured_at=datetime(2025, 6, 15, 18, 0, 0, tzinfo=timezone.utc)
        )
        store.insert(r1)
        store.insert(r2)
        store.insert(r3)
        results = store.query(
            start=datetime(2025, 6, 15, 10, 0, 0, tzinfo=timezone.utc),
            end=datetime(2025, 6, 15, 15, 0, 0, tzinfo=timezone.utc),
        )
        assert len(results) == 1
        assert results[0].id == r2.id

    def test_query_by_media_type(self, store):
        r1 = _make_record(media_type=MediaType.IMAGE)
        r2 = _make_record(media_type=MediaType.VIDEO, format="avi")
        store.insert(r1)
        store.insert(r2)
        results = store.query(media_type=MediaType.VIDEO)
        assert len(results) == 1
        assert results[0].id == r2.id

    def test_query_by_device_id(self, store):
        r1 = _make_record(device_id="pi-01")
        r2 = _make_record(device_id="pi-02")
        store.insert(r1)
        store.insert(r2)
        results = store.query(device_id="pi-01")
        assert len(results) == 1
        assert results[0].id == r1.id

    def test_query_by_labels_any_match(self, store):
        r1 = _make_record(labels=["person", "car"])
        r2 = _make_record(labels=["dog"])
        r3 = _make_record(labels=["car", "truck"])
        store.insert(r1)
        store.insert(r2)
        store.insert(r3)
        results = store.query(labels=["person", "dog"])
        ids = {r.id for r in results}
        assert r1.id in ids
        assert r2.id in ids
        assert r3.id not in ids

    def test_query_with_limit_and_offset(self, store):
        for i in range(5):
            store.insert(
                _make_record(
                    captured_at=datetime(2025, 6, 15, i, 0, 0, tzinfo=timezone.utc)
                )
            )
        results = store.query(limit=2, offset=1)
        assert len(results) == 2

    def test_query_combined_filters(self, store):
        r1 = _make_record(
            media_type=MediaType.IMAGE,
            device_id="pi-01",
            labels=["person"],
            captured_at=datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        )
        r2 = _make_record(
            media_type=MediaType.VIDEO,
            device_id="pi-01",
            labels=["person"],
            captured_at=datetime(2025, 6, 15, 14, 0, 0, tzinfo=timezone.utc),
        )
        store.insert(r1)
        store.insert(r2)
        results = store.query(
            media_type=MediaType.IMAGE, device_id="pi-01", labels=["person"]
        )
        assert len(results) == 1
        assert results[0].id == r1.id


class TestSearchSimilar:
    def test_returns_similar_records(self, store):
        r1 = _make_record(
            embedding=[1.0, 0.0, 0.0],
            embedding_model="test-model",
            embedding_dim=3,
        )
        r2 = _make_record(
            embedding=[0.0, 1.0, 0.0],
            embedding_model="test-model",
            embedding_dim=3,
        )
        store.insert(r1)
        store.insert(r2)

        results = store.search_similar([1.0, 0.0, 0.0], model="test-model")
        assert len(results) == 2
        assert results[0].id == r1.id  # most similar to [1,0,0]

    def test_threshold_filters_results(self, store):
        r1 = _make_record(
            embedding=[1.0, 0.0, 0.0],
            embedding_model="test-model",
            embedding_dim=3,
        )
        r2 = _make_record(
            embedding=[0.0, 1.0, 0.0],
            embedding_model="test-model",
            embedding_dim=3,
        )
        store.insert(r1)
        store.insert(r2)

        results = store.search_similar(
            [1.0, 0.0, 0.0], model="test-model", threshold=0.9
        )
        assert len(results) == 1
        assert results[0].id == r1.id

    def test_model_scoping(self, store):
        r1 = _make_record(
            embedding=[1.0, 0.0],
            embedding_model="model-a",
            embedding_dim=2,
        )
        r2 = _make_record(
            embedding=[1.0, 0.0],
            embedding_model="model-b",
            embedding_dim=2,
        )
        store.insert(r1)
        store.insert(r2)

        results = store.search_similar([1.0, 0.0], model="model-a")
        assert len(results) == 1
        assert results[0].id == r1.id

    def test_limit(self, store):
        for _ in range(5):
            store.insert(
                _make_record(
                    embedding=[1.0, 0.0],
                    embedding_model="test-model",
                    embedding_dim=2,
                )
            )
        results = store.search_similar([1.0, 0.0], model="test-model", limit=3)
        assert len(results) == 3

    def test_no_results_for_unknown_model(self, store):
        r1 = _make_record(
            embedding=[1.0, 0.0],
            embedding_model="model-a",
            embedding_dim=2,
        )
        store.insert(r1)
        results = store.search_similar([1.0, 0.0], model="unknown-model")
        assert results == []

    def test_excludes_records_without_embedding(self, store):
        r1 = _make_record()  # no embedding
        r2 = _make_record(
            embedding=[1.0, 0.0],
            embedding_model="test-model",
            embedding_dim=2,
        )
        store.insert(r1)
        store.insert(r2)
        results = store.search_similar([1.0, 0.0], model="test-model")
        assert len(results) == 1
        assert results[0].id == r2.id


class TestSchemaMigration:
    def test_migrates_pre_version_database(self, tmp_path):
        db_path = tmp_path / "old.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE media (
                id          TEXT PRIMARY KEY,
                media_type  TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                inserted_at TEXT NOT NULL,
                duration    REAL,
                format      TEXT NOT NULL,
                size        INTEGER NOT NULL,
                device_id   TEXT,
                labels      TEXT NOT NULL DEFAULT '[]',
                description TEXT,
                embedding   TEXT
            );
        """)
        conn.execute(
            "INSERT INTO media VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "old-id",
                "image",
                "2025-01-01T00:00:00+00:00",
                "2025-01-01T00:00:01+00:00",
                None,
                "jpg",
                100,
                None,
                "[]",
                None,
                None,
            ),
        )
        conn.commit()
        conn.close()

        store = SQLiteMetadataStore(db_path=db_path)
        record = store.get("old-id")
        assert record.id == "old-id"
        assert record.embedding_model is None
        assert record.embedding_dim is None
        assert record.content_hash is None
        store.close()
