"""SpectatorDB — media storage and retrieval facade."""

import hashlib
import pathlib

from datetime import datetime, timezone
from types import TracebackType
from typing import Self

from spectatordb import exif
from spectatordb.metadata.metadata_store import MetadataStore
from spectatordb.models import (
    MediaRecord,
    MediaType,
    ReconcileReport,
    _UnsetType,
    UNSET,
)
from spectatordb.storage.storage import SaveMode, Storage

# File extensions recognized by :meth:`SpectatorDB.import_dir`, keyed without
# the leading dot and matched case-insensitively.
_IMAGE_EXTENSIONS = frozenset(
    {"jpg", "jpeg", "png", "gif", "bmp", "webp", "tif", "tiff", "heic", "heif"}
)
_VIDEO_EXTENSIONS = frozenset(
    {"mp4", "mov", "avi", "mkv", "webm", "m4v", "mpg", "mpeg", "3gp"}
)

_HASH_CHUNK_SIZE = 1 << 20  # 1 MiB


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _media_type_for(file: pathlib.Path) -> MediaType | None:
    """Infer a :class:`MediaType` from a file extension, or ``None``."""
    ext = file.suffix.lstrip(".").lower()
    if ext in _IMAGE_EXTENSIONS:
        return MediaType.IMAGE
    if ext in _VIDEO_EXTENSIONS:
        return MediaType.VIDEO
    return None


def _hash_file(file: pathlib.Path) -> str:
    """Return the SHA-256 hex digest of a file's contents (streamed)."""
    digest = hashlib.sha256()
    with open(file, "rb") as f:
        for chunk in iter(lambda: f.read(_HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_captured_at(
    file: pathlib.Path,
    media_type: MediaType,
    captured_at: datetime | None,
) -> datetime:
    """Determine a capture time, falling back to EXIF then file mtime.

    An explicit ``captured_at`` always wins. Otherwise, for images we try the
    EXIF ``DateTimeOriginal`` (treated as UTC, since EXIF carries no timezone),
    and finally fall back to the file's modification time.
    """
    if captured_at is not None:
        return captured_at
    if media_type == MediaType.IMAGE:
        exif_dt = exif.read_captured_at(file)
        if exif_dt is not None:
            return exif_dt
    return datetime.fromtimestamp(file.stat().st_mtime, tz=timezone.utc)


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

    def close(self) -> None:
        """Release resources held by the storage and metadata backends.

        After ``close()`` the instance must not be used again. Safe to call
        more than once. ``SpectatorDB`` is also a context manager, so prefer
        ``with SpectatorDB(...) as db:`` where possible.
        """
        self._metadata_store.close()
        self._storage.close()

    def __enter__(self) -> Self:
        """Enter the runtime context and return this instance."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Exit the runtime context, closing backend resources."""
        self.close()

    def insert(
        self,
        file: pathlib.Path,
        media_type: MediaType,
        captured_at: datetime | None = None,
        *,
        duration: float | None = None,
        device_id: str | None = None,
        labels: list[str] | None = None,
        description: str | None = None,
        embedding: list[float] | None = None,
        embedding_model: str | None = None,
        content_hash: str | None = None,
        skip_duplicates: bool = False,
    ) -> str | None:
        """Insert a media file and its metadata.

        The file is saved to storage first; if the metadata insert then fails,
        the saved file is deleted as a compensating action so no orphaned file
        is left behind.

        If ``captured_at`` is omitted, it is recovered from the image's EXIF
        ``DateTimeOriginal`` and, failing that, the file's modification time.
        The resolved value is normalized to UTC before storage.

        A SHA-256 ``content_hash`` is computed from the file when not supplied,
        enabling deduplication. With ``skip_duplicates=True`` an insert whose
        hash already exists is skipped and ``None`` is returned.

        Parameters
        ----------
        file : pathlib.Path
            Path to the media file to store.
        media_type : MediaType
            The type of media (IMAGE or VIDEO).
        captured_at : datetime | None
            When the media was captured. If ``None``, resolved from EXIF then
            file mtime.
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
            SHA-256 content hash for deduplication. Computed from ``file`` when
            omitted.
        skip_duplicates : bool
            When ``True``, skip the insert (returning ``None``) if a record
            with the same ``content_hash`` already exists.

        Returns
        -------
        str | None
            The ID of the inserted record, or ``None`` if it was skipped as a
            duplicate.
        """
        captured_at = _resolve_captured_at(file, media_type, captured_at)
        if content_hash is None:
            content_hash = _hash_file(file)
        if skip_duplicates and self._metadata_store.exists(content_hash):
            return None

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

    def import_dir(
        self,
        directory: pathlib.Path,
        *,
        recursive: bool = True,
        skip_duplicates: bool = True,
        device_id: str | None = None,
    ) -> list[str]:
        """Bulk-import every recognized media file under a directory.

        Files are matched by extension (see the module's image/video extension
        sets); anything unrecognized is ignored. Each file's capture time is
        resolved from EXIF or mtime as in :meth:`insert`.

        Parameters
        ----------
        directory : pathlib.Path
            The folder to import from.
        recursive : bool
            Recurse into subdirectories (default ``True``).
        skip_duplicates : bool
            Skip files whose content hash already exists (default ``True``;
            personal libraries tend to contain many duplicates).
        device_id : str | None
            Optional device id to tag every imported record with.

        Returns
        -------
        list[str]
            The IDs of the records actually inserted, in import order
            (skipped duplicates are omitted).
        """
        paths = directory.rglob("*") if recursive else directory.iterdir()
        inserted: list[str] = []
        for path in sorted(paths):
            if not path.is_file():
                continue
            media_type = _media_type_for(path)
            if media_type is None:
                continue
            record_id = self.insert(
                path,
                media_type,
                device_id=device_id,
                skip_duplicates=skip_duplicates,
            )
            if record_id is not None:
                inserted.append(record_id)
        return inserted

    def exists(self, content_hash: str) -> bool:
        """Return whether any stored record has the given SHA-256 content hash.

        Parameters
        ----------
        content_hash : str
            The SHA-256 hex digest to look for.

        Returns
        -------
        bool
            ``True`` if a matching record exists.
        """
        return self._metadata_store.exists(content_hash)

    def update_enrichment(
        self,
        id: str,
        *,
        labels: list[str] | _UnsetType = UNSET,
        description: str | None | _UnsetType = UNSET,
        embedding: list[float] | None | _UnsetType = UNSET,
        embedding_model: str | None | _UnsetType = UNSET,
    ) -> None:
        """Update enrichment fields of a stored record, skipping unset parameters.

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

    def update_metadata(
        self,
        id: str,
        *,
        captured_at: datetime | _UnsetType = UNSET,
        device_id: str | None | _UnsetType = UNSET,
        duration: float | None | _UnsetType = UNSET,
    ) -> None:
        """Correct intrinsic metadata of a stored record, skipping unset params.

        Use this to fix a wrong capture time or device attribution after the
        fact; enrichment fields (labels, description, embedding) go through
        :meth:`update_enrichment`. Only non-``UNSET`` fields are written and
        ``captured_at`` is normalized to UTC.

        Parameters
        ----------
        id : str
            The record ID.
        captured_at : datetime | UNSET
            Corrected capture time, or ``UNSET`` to leave unchanged.
        device_id : str | None | UNSET
            New device id (``None`` clears it), or ``UNSET`` to leave unchanged.
        duration : float | None | UNSET
            New duration (``None`` clears it), or ``UNSET`` to leave unchanged.

        Raises
        ------
        KeyError
            If no record with the given ID exists.
        """
        self._metadata_store.update_metadata(
            id,
            captured_at=captured_at,
            device_id=device_id,
            duration=duration,
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

    def count(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        media_type: MediaType | None = None,
        device_id: str | None = None,
        labels: list[str] | None = None,
    ) -> int:
        """Count records matching composable filters.

        Accepts the same filters as :meth:`query` (AND-combined; ``labels`` is
        ANY-match) and returns the count — handy for paging a gallery without
        loading every record.

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

        Returns
        -------
        int
            The number of matching records.
        """
        return self._metadata_store.count(
            start=start,
            end=end,
            media_type=media_type,
            device_id=device_id,
            labels=labels,
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

        Raises
        ------
        ValueError
            If ``embedding``'s dimension does not match the dimension of the
            stored vectors for ``model``.
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
        dangling = [
            r.id for r in all_records if f"{r.id}.{r.format}" not in stored_names
        ]

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
