"""SQLite-backed metadata store."""

import json
import pathlib
import sqlite3

from datetime import datetime, timezone
from typing import override

from spectatordb.metadata.metadata_store import MetadataStore
from spectatordb.models import MediaRecord, MediaType


class SQLiteMetadataStore(MetadataStore):
    """SQLite implementation of :class:`MetadataStore`.

    Stores structured metadata in SQLite. Vector similarity search via
    ``search_similar`` requires the optional ``sqlite-vec`` extension;
    if it is not installed, ``search_similar`` raises ``NotImplementedError``.

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
        self._create_tables()

    def close(self) -> None:
        """Close the database connection."""
        self._connection.close()

    def _create_tables(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS media (
                id          TEXT PRIMARY KEY,
                media_type  TEXT NOT NULL CHECK(media_type IN ('image', 'video')),
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

            CREATE INDEX IF NOT EXISTS idx_media_captured_at
                ON media(captured_at);
            CREATE INDEX IF NOT EXISTS idx_media_media_type
                ON media(media_type);
            CREATE INDEX IF NOT EXISTS idx_media_device_id
                ON media(device_id);
            """
        )

    def _row_to_record(self, row: sqlite3.Row) -> MediaRecord:
        return MediaRecord(
            id=row["id"],
            media_type=MediaType(row["media_type"]),
            captured_at=datetime.fromisoformat(row["captured_at"]),
            inserted_at=datetime.fromisoformat(row["inserted_at"]),
            duration=row["duration"],
            format=row["format"],
            size=row["size"],
            device_id=row["device_id"],
            labels=json.loads(row["labels"]),
            description=row["description"],
            embedding=json.loads(row["embedding"]) if row["embedding"] else None,
        )

    @override
    def insert(self, record: MediaRecord) -> str:
        now = datetime.now(timezone.utc)
        record.inserted_at = now

        self._connection.execute(
            """
            INSERT INTO media (
                id, media_type, captured_at, inserted_at, duration,
                format, size, device_id, labels, description, embedding
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                json.dumps(record.embedding) if record.embedding else None,
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
        cursor = self._connection.execute("DELETE FROM media WHERE id = ?", (id,))
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
            params.append(start.isoformat())
        if end is not None:
            clauses.append("captured_at < ?")
            params.append(end.isoformat())
        if media_type is not None:
            clauses.append("media_type = ?")
            params.append(media_type.value)
        if device_id is not None:
            clauses.append("device_id = ?")
            params.append(device_id)
        if labels:
            label_clauses = []
            for label in labels:
                label_clauses.append("EXISTS (SELECT 1 FROM json_each(labels) WHERE value = ?)")
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
        limit: int | None = None,
        threshold: float | None = None,
    ) -> list[MediaRecord]:
        raise NotImplementedError(
            "Vector similarity search requires the sqlite-vec extension. "
            "This feature is not yet implemented."
        )
