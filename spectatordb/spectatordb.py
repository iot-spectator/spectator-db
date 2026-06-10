"""SpectatorDB — media storage and retrieval facade."""

import pathlib

from datetime import datetime

from spectatordb.metadata.metadata_store import MetadataStore
from spectatordb.models import MediaRecord, MediaType
from spectatordb.storage.storage import SaveMode, Storage


class SpectatorDB:
    """Main class for managing media data storage and retrieval.

    Orchestrates a :class:`Storage` backend (file storage) and a
    :class:`MetadataStore` backend (structured metadata) behind a
    single, unified API.

    Parameters
    ----------
    storage : Storage
        The file storage backend.
    metadata_store : MetadataStore
        The metadata storage backend.
    """

    def __init__(self, storage: Storage, metadata_store: MetadataStore) -> None:
        self._storage = storage
        self._metadata_store = metadata_store

    def insert(
        self,
        file: pathlib.Path,
        media_type: MediaType,
        captured_at: datetime,
        *,
        duration: float | None = None,
        device_id: str | None = None,
        labels: list[str] | None = None,
        description: str | None = None,
        embedding: list[float] | None = None,
    ) -> str:
        """Insert a media file and its metadata.

        Parameters
        ----------
        file : pathlib.Path
            Path to the media file to store.
        media_type : MediaType
            The type of media (IMAGE or VIDEO).
        captured_at : datetime
            When the media was captured.
        duration : float | None
            Duration in seconds (video only).
        device_id : str | None
            Identifier of the capturing device.
        labels : list[str] | None
            Semantic labels, e.g. ``["person", "car"]``.
        description : str | None
            Text summary of the media content.
        embedding : list[float] | None
            Vector embedding for semantic search.

        Returns
        -------
        str
            The ID of the inserted record.
        """
        record = MediaRecord(
            media_type=media_type,
            captured_at=captured_at,
            format=file.suffix.lstrip("."),
            size=file.stat().st_size,
            duration=duration,
            device_id=device_id,
            labels=labels or [],
            description=description,
            embedding=embedding,
        )

        storage_name = f"{record.id}.{record.format}"
        self._storage.save(file, mode=SaveMode.COPY, name=storage_name)
        self._metadata_store.insert(record)
        return record.id

    def delete(self, id: str) -> None:
        """Delete a media record and its file.

        Parameters
        ----------
        id : str
            The record ID.

        Raises
        ------
        KeyError
            If no record with the given ID exists.
        """
        record = self._metadata_store.get(id)
        storage_name = f"{record.id}.{record.format}"
        self._metadata_store.delete(id)
        self._storage.delete(storage_name)

    def get(self, id: str) -> MediaRecord:
        """Get a single record by ID.

        Parameters
        ----------
        id : str
            The record ID.

        Returns
        -------
        MediaRecord
            The matching record.

        Raises
        ------
        KeyError
            If no record with the given ID exists.
        """
        return self._metadata_store.get(id)

    def retrieve(self, id: str, dest: pathlib.Path) -> None:
        """Copy a media file to the given destination.

        Parameters
        ----------
        id : str
            The record ID.
        dest : pathlib.Path
            Destination path where the file will be copied.

        Raises
        ------
        KeyError
            If no record with the given ID exists.
        """
        record = self._metadata_store.get(id)
        storage_name = f"{record.id}.{record.format}"
        self._storage.retrieve(storage_name, dest)

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
        """Query records with composable filters.

        All parameters are optional. When multiple filters are provided, they
        are combined with AND semantics. ``labels`` uses ANY-match semantics.

        Parameters
        ----------
        start : datetime | None
            Include records captured at or after this time.
        end : datetime | None
            Include records captured before this time.
        media_type : MediaType | None
            Filter by media type.
        device_id : str | None
            Filter by device ID.
        labels : list[str] | None
            Filter by labels (ANY-match).
        limit : int | None
            Maximum number of records to return.
        offset : int | None
            Number of records to skip.

        Returns
        -------
        list[MediaRecord]
            Matching records ordered by ``captured_at`` descending.
        """
        return self._metadata_store.query(
            start=start,
            end=end,
            media_type=media_type,
            device_id=device_id,
            labels=labels,
            limit=limit,
            offset=offset,
        )

    def search_similar(
        self,
        embedding: list[float],
        *,
        limit: int | None = None,
        threshold: float | None = None,
    ) -> list[MediaRecord]:
        """Search for records similar to the given embedding.

        Parameters
        ----------
        embedding : list[float]
            The query embedding vector.
        limit : int | None
            Maximum number of results.
        threshold : float | None
            Minimum similarity score (0-1).

        Returns
        -------
        list[MediaRecord]
            Matching records ordered by similarity descending.
        """
        return self._metadata_store.search_similar(
            embedding, limit=limit, threshold=threshold
        )
