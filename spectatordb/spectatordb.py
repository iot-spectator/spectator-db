"""SpectatorDB — media storage and retrieval facade."""

import pathlib

from datetime import datetime, timezone

from spectatordb.metadata.metadata_store import MetadataStore
from spectatordb.models import MediaRecord, MediaType, ReconcileReport, _UnsetType, UNSET
from spectatordb.storage.storage import SaveMode, Storage


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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
        embedding_model: str | None = None,
        content_hash: str | None = None,
    ) -> str:
        """Insert a media file and its metadata.

        The file is saved to storage first; if the metadata insert then fails,
        the saved file is deleted as a compensating action so no orphaned file
        is left behind.

        ``captured_at`` is normalized to UTC before storage.

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
        embedding_model : str | None
            Identity of the model that produced the embedding.
        content_hash : str | None
            SHA-256 content hash for optional deduplication.

        Returns
        -------
        str
            The ID of the inserted record.
        """
        embedding_dim = len(embedding) if embedding is not None else None
        record = MediaRecord(
            media_type=media_type,
            captured_at=_to_utc(captured_at),
            format=file.suffix.lstrip("."),
            size=file.stat().st_size,
            duration=duration,
            device_id=device_id,
            labels=labels or [],
            description=description,
            embedding=embedding,
            embedding_model=embedding_model,
            embedding_dim=embedding_dim,
            content_hash=content_hash,
        )

        storage_name = f"{record.id}.{record.format}"
        self._storage.save(file, mode=SaveMode.COPY, name=storage_name)
        try:
            self._metadata_store.insert(record)
        except Exception:
            self._storage.delete(storage_name)
            raise
        return record.id

    def update_enrichment(
        self,
        id: str,
        *,
        labels: list[str] | _UnsetType = UNSET,
        description: str | None | _UnsetType = UNSET,
        embedding: list[float] | None | _UnsetType = UNSET,
        embedding_model: str | None | _UnsetType = UNSET,
    ) -> None:
        """Partially update the enrichment fields of a stored record.

        Only fields that are not ``UNSET`` are written. ``embedding`` and
        ``embedding_model`` must be updated together.

        Parameters
        ----------
        id : str
            The record ID.
        labels : list[str] | UNSET
            New label list, or ``UNSET`` to leave unchanged.
        description : str | None | UNSET
            New description, or ``UNSET`` to leave unchanged.
        embedding : list[float] | None | UNSET
            New embedding vector, or ``UNSET`` to leave unchanged.
        embedding_model : str | None | UNSET
            New embedding model identity, or ``UNSET`` to leave unchanged.

        Raises
        ------
        KeyError
            If no record with the given ID exists.
        ValueError
            If ``embedding`` and ``embedding_model`` are not updated together.
        """
        self._metadata_store.update_enrichment(
            id,
            labels=labels,
            description=description,
            embedding=embedding,
            embedding_model=embedding_model,
        )

    def delete(self, id: str) -> None:
        """Delete a media record and its file.

        Metadata is deleted first; the file deletion then tolerates a
        missing file so that a crash between the two steps cannot leave
        the system in a permanently broken state.

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
        model: str,
        limit: int | None = None,
        threshold: float | None = None,
    ) -> list[MediaRecord]:
        """Search for records similar to the given embedding.

        Only records whose ``embedding_model`` matches ``model`` are compared.
        Similarity is computed as cosine similarity.

        Parameters
        ----------
        embedding : list[float]
            The query embedding vector.
        model : str
            The embedding model identity; only records sharing this model
            are considered.
        limit : int | None
            Maximum number of results.
        threshold : float | None
            Minimum cosine similarity score (0–1) to include a result.

        Returns
        -------
        list[MediaRecord]
            Matching records ordered by similarity descending.
        """
        return self._metadata_store.search_similar(
            embedding, model=model, limit=limit, threshold=threshold
        )

    def reconcile(self) -> ReconcileReport:
        """Sweep storage and metadata for orphaned files and dangling rows.

        An *orphaned file* is a file in storage with no matching metadata row.
        A *dangling row* is a metadata row whose backing file is missing.
        Both are deleted and counted in the returned report.

        Returns
        -------
        ReconcileReport
            Summary of what was found and cleaned up.
        """
        stored_names = {f.name for f in self._storage.list_all()}
        all_records = self._metadata_store.query()

        expected_names = {f"{r.id}.{r.format}" for r in all_records}
        orphaned = sorted(stored_names - expected_names)
        dangling = [r.id for r in all_records if f"{r.id}.{r.format}" not in stored_names]

        report = ReconcileReport(
            orphaned_files=orphaned,
            dangling_rows=dangling,
        )

        for name in orphaned:
            self._storage.delete(name)
            report.deleted_files += 1

        for record_id in dangling:
            self._metadata_store.delete(record_id)
            report.deleted_rows += 1

        return report
