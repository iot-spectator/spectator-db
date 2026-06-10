import pytest

from datetime import datetime, timezone

from spectatordb.metadata.sqlite_metadata_store import SQLiteMetadataStore
from spectatordb.models import MediaRecord, MediaType


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
        )
        store.insert(record)
        result = store.get(record.id)
        assert result.media_type == MediaType.VIDEO
        assert result.duration == 10.5
        assert result.description == "A dog running"
        assert result.embedding == [0.1, 0.2, 0.3]


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


class TestQuery:
    def test_query_no_filters(self, store):
        r1 = _make_record(captured_at=datetime(2025, 6, 15, 10, 0, 0, tzinfo=timezone.utc))
        r2 = _make_record(captured_at=datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc))
        store.insert(r1)
        store.insert(r2)
        results = store.query()
        assert len(results) == 2
        # Ordered by captured_at descending
        assert results[0].id == r2.id
        assert results[1].id == r1.id

    def test_query_by_time_range(self, store):
        r1 = _make_record(captured_at=datetime(2025, 6, 15, 8, 0, 0, tzinfo=timezone.utc))
        r2 = _make_record(captured_at=datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc))
        r3 = _make_record(captured_at=datetime(2025, 6, 15, 18, 0, 0, tzinfo=timezone.utc))
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
            store.insert(_make_record(
                captured_at=datetime(2025, 6, 15, i, 0, 0, tzinfo=timezone.utc)
            ))
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
        results = store.query(media_type=MediaType.IMAGE, device_id="pi-01", labels=["person"])
        assert len(results) == 1
        assert results[0].id == r1.id


class TestSearchSimilar:
    def test_search_similar_not_implemented(self, store):
        with pytest.raises(NotImplementedError):
            store.search_similar([0.1, 0.2, 0.3])
