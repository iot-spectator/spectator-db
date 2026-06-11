"""SQLite-backed metadata store."""

import json
import pathlib
import sqlite3
import threading

from datetime import datetime, timezone
from typing import override

from spectatordb.metadata.metadata_store import MetadataStore
from spectatordb.models import MediaRecord, MediaType, _UnsetType, UNSET


_SCHEMA_VERSION = 1


def _to_utc(dt: datetime) -> datetime:
    """Return a tz-aware UTC datetime, treating naive datetimes as UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class SQLiteMetadataStore(MetadataStore):
    """SQLite implementation of :class:`MetadataStore`.

    Stores structured metadata in SQLite. Vector similarity search is
    implemented as pure-Python brute-force cosine similarity over records
    sharing the same embedding model.

    Write operations are serialized with a :class:`threading.Lock` so the
    store is safe for the expected low-write, motion-triggered workload with
    one instance per process. Reads are lock-free; WAL mode allows concurrent
    reads alongside writes.

    Parameters
    ----------
    db_path : pathlib.Path
        Path to the SQLite database file. Created if it does not exist.
    """

    def __init__(self, db_path: pathlib.Path) -> None:
        self._db_path = db_path
        self._connection = sqlite3.connect(
            str(db_path),
            detect_types=sqlite3.PARSE_DECLTYPES,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        self._init_schema()

    def close(self) -> None:
        """Close the database connection."""
        self._connection.close()

    # ------------------------------------------------------------------
    # Schema management
    # ------------------------------------------------------------------

    def _get_schema_version(self) -> int:
        return int(self._connection.execute("PRAGMA user_version").fetchone()[0])

    def _init_schema(self) -> None:
        version = self._get_schema_version()
        if version == 0:
            has_table = bool(
                self._connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='media'"
                ).fetchone()
            )
            if has_table:
                self._migrate(from_version=0)
            else:
                self._create_tables()
                self._connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
                self._connection.commit()
        elif version < _SCHEMA_VERSION:
            self._migrate(from_version=version)

    def _create_tables(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS media (
                id              TEXT PRIMARY KEY,
                media_type      TEXT NOT NULL CHECK(media_type IN ('image', 'video')),
                captured_at     TEXT NOT NULL,
                inserted_at     TEXT NOT NULL,
                duration        REAL,
                format          TEXT NOT NULL,
                size            INTEGER NOT NULL,
                device_id       TEXT,
                labels          TEXT NOT NULL DEFAULT '[]',
                description     TEXT,
                embedding       TEXT,
                embedding_model TEXT,
                embedding_dim   INTEGER,
                content_hash    TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_media_captured_at
                ON media(captured_at);
            CREATE INDEX IF NOT EXISTS idx_media_media_type
                ON media(media_type);
            CREATE INDEX IF NOT EXISTS idx_media_device_id
                ON media(device_id);
            """
        )

    def _migrate(self, from_version: int) -> None:
        if from_version < 1:
            self._connection.execute(
                "ALTER TABLE media ADD COLUMN embedding_model TEXT"
            )
            self._connection.execute(
                "ALTER TABLE media ADD COLUMN embedding_dim INTEGER"
            )
            self._connection.execute(
                "ALTER TABLE media ADD COLUMN content_hash TEXT"
            )
            self._connection.execute(f"PRAGMA user_version = 1")
            self._connection.commit()

    # ------------------------------------------------------------------
    # Row mapping
    # ------------------------------------------------------------------

    def _row_to_record(self, row: sqlite3.Row) -> MediaRecord:
        captured_at = datetime.fromisoformat(row["captured_at"])
        if captured_at.tzinfo is None:
            captured_at = captured_at.replace(tzinfo=timezone.utc)

        embedding_raw = row["embedding"]
        embedding: list[float] | None = json.loads(embedding_raw) if embedding_raw else None
        embedding_model: str | None = row["embedding_model"]
        embedding_dim_raw = row["embedding_dim"]
        embedding_dim: int | None = int(embedding_dim_raw) if embedding_dim_raw is not None else None

        return MediaRecord(
            id=row["id"],
            media_type=MediaType(row["media_type"]),
            captured_at=captured_at,
            inserted_at=datetime.fromisoformat(row["inserted_at"]),
            duration=row["duration"],
            format=row["format"],
            size=row["size"],
            device_id=row["device_id"],
            labels=json.loads(row["labels"]),
            description=row["description"],
            embedding=embedding,
            embedding_model=embedding_model,
            embedding_dim=embedding_dim,
            content_hash=row["content_hash"],
        )

    # ------------------------------------------------------------------
    # MetadataStore interface
    # ------------------------------------------------------------------

    @override
    def insert(self, record: MediaRecord) -> str:
        now = datetime.now(timezone.utc)
        record.inserted_at = now
        record.captured_at = _to_utc(record.captured_at)

        with self._lock:
            self._connection.execute(
                """
                INSERT INTO media (
                    id, media_type, captured_at, inserted_at, duration,
                    format, size, device_id, labels, description,
                    embedding, embedding_model, embedding_dim, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.media_type.value,
                    record.captured_at.isoformat(),
                    now.isoformat(),
                    record.duration,
                    record.format,
                    record.size,
                    record.device_id,
                    json.dumps(record.labels),
                    record.description,
                    json.dumps(record.embedding) if record.embedding is not None else None,
                    record.embedding_model,
                    record.embedding_dim,
                    record.content_hash,
                ),
            )
            self._connection.commit()
        return record.id

    @override
    def get(self, id: str) -> MediaRecord:
        cursor = self._connection.execute("SELECT * FROM media WHERE id = ?", (id,))
        row = cursor.fetchone()
        if row is None:
            raise KeyError(f"No record with id '{id}'")
        return self._row_to_record(row)

    @override
    def delete(self, id: str) -> None:
        with self._lock:
            cursor = self._connection.execute("DELETE FROM media WHERE id = ?", (id,))
            self._connection.commit()
        if cursor.rowcount == 0:
            raise KeyError(f"No record with id '{id}'")

    @override
    def update_enrichment(
        self,
        id: str,
        *,
        labels: list[str] | _UnsetType = UNSET,
        description: str | None | _UnsetType = UNSET,
        embedding: list[float] | None | _UnsetType = UNSET,
        embedding_model: str | None | _UnsetType = UNSET,
    ) -> None:
        embedding_unset = isinstance(embedding, _UnsetType)
        model_unset = isinstance(embedding_model, _UnsetType)
        if embedding_unset != model_unset:
            raise ValueError(
                "embedding and embedding_model must be updated together"
            )

        clauses: list[str] = []
        params: list[object] = []

        if not isinstance(labels, _UnsetType):
            clauses.append("labels = ?")
            params.append(json.dumps(labels))

        if not isinstance(description, _UnsetType):
            clauses.append("description = ?")
            params.append(description)

        if not embedding_unset:
            if embedding is None:
                clauses.extend(["embedding = ?", "embedding_model = ?", "embedding_dim = ?"])
                params.extend([None, None, None])
            else:
                if not isinstance(embedding, list):
                    raise TypeError("embedding must be a list of floats or None")
                dim = len(embedding)
                clauses.extend(["embedding = ?", "embedding_model = ?", "embedding_dim = ?"])
                params.extend([json.dumps(embedding), embedding_model, dim])

        if not clauses:
            self.get(id)  # raise KeyError if record doesn't exist
            return

        params.append(id)
        sql = f"UPDATE media SET {', '.join(clauses)} WHERE id = ?"

        with self._lock:
            cursor = self._connection.execute(sql, params)
            self._connection.commit()
        if cursor.rowcount == 0:
            raise KeyError(f"No record with id '{id}'")

    @override
    def query(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        media_type: MediaType | None = None,
        device_id: str | None = None,
        labels: list[str] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[MediaRecord]:
        clauses: list[str] = []
        params: list[str | int | float] = []

        if start is not None:
            clauses.append("captured_at >= ?")
            params.append(_to_utc(start).isoformat())
        if end is not None:
            clauses.append("captured_at < ?")
            params.append(_to_utc(end).isoformat())
        if media_type is not None:
            clauses.append("media_type = ?")
            params.append(media_type.value)
        if device_id is not None:
            clauses.append("device_id = ?")
            params.append(device_id)
        if labels:
            label_clauses = []
            for label in labels:
                label_clauses.append(
                    "EXISTS (SELECT 1 FROM json_each(labels) WHERE value = ?)"
                )
                params.append(label)
            clauses.append(f"({' OR '.join(label_clauses)})")

        sql = "SELECT * FROM media"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY captured_at DESC"

        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        if offset is not None:
            sql += " OFFSET ?"
            params.append(offset)

        cursor = self._connection.execute(sql, params)
        return [self._row_to_record(row) for row in cursor.fetchall()]

    @override
    def search_similar(
        self,
        embedding: list[float],
        *,
        model: str,
        limit: int | None = None,
        threshold: float | None = None,
    ) -> list[MediaRecord]:
        cursor = self._connection.execute(
            "SELECT * FROM media WHERE embedding_model = ? AND embedding IS NOT NULL",
            (model,),
        )
        rows = cursor.fetchall()

        scored: list[tuple[float, MediaRecord]] = []
        for row in rows:
            record = self._row_to_record(row)
            if record.embedding is None:
                continue
            score = _cosine_similarity(embedding, record.embedding)
            if threshold is None or score >= threshold:
                scored.append((score, record))

        scored.sort(key=lambda t: t[0], reverse=True)

        if limit is not None:
            scored = scored[:limit]

        return [record for _, record in scored]
