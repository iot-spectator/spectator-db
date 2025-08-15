import pathlib

from typing import Optional
from datetime import datetime

from spectatordb import MediaType
from spectatordb import sqlite_connector
from spectatordb import storage


class SpectatorDB:

    def __init__(
        self, storage: storage.Storage, sql_connector: sqlite_connector.SQLiteConnector
    ):
        """Initialize the SpectatorDB with a storage backend.

        Parameters
        ----------
        storage : storage.Storage
            An instance of a storage backend that implements the Storage interface.
        sql_connector : sql_connector.SQLiteConnector
            An instance of the SQLiteConnector for database operations.
        """
        self._storage = storage
        self._sql_connector = sql_connector

    def _create_metadata_db(self) -> None:
        CREATE_STATEMENT = """
            CREATE TABLE IF NOT EXISTS metadata (
                name text PRIMARY KEY,
                path text NOT NULL,
                size integer NOT NULL,
                media_type text NOT NULL CHECK(media_type IN ('VIDEO', 'IMAGE')),
                format text NOT NULL,
                description text,
                inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            );"""
        self._sql_connector.execute_query(query=CREATE_STATEMENT)

    def insert(
        self, file: pathlib.Path, media_type: MediaType, description: Optional[str]
    ) -> None:
        """Insert a media data.

        Parameters
        ----------
        file : pathlib.Path
            The full path of the file to be inserted.
        media_type : MediaType
            The type of the data, either VIDEO or IMAGE.
        """
        INSERT_STATEMENT = """
            INSERT INTO metadata (
                name,
                path,
                size,
                media_type,
                format,
                description,
                inserted_at,
                updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """
        self._storage.save(file, mode=storage.SaveMode.COPY)
        self._sql_connector.execute_query(
            query=INSERT_STATEMENT,
            params=(
                file.name,
                str(file),
                file.stat().st_size,
                media_type.value,
                file.suffix.lstrip("."),
                description or "",
                datetime.now().isoformat(),
                datetime.now().isoformat(),
            ),
        )

    def delete(self, name: str) -> None:
        """Delete a file.

        Parameters
        ----------
        name : str
            The name of the file to delete.
        """
        DELETE_STATEMENT = """
            DELETE FROM metadata WHERE name = ?;
            """
        self._sql_connector.execute_query(query=DELETE_STATEMENT, params=(name,))
        self._storage.delete(name=name)
