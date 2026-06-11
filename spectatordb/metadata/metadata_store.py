"""Abstract base class for metadata storage backends."""

import abc

from datetime import datetime

from spectatordb.models import MediaRecord, MediaType, _UnsetType, UNSET


class MetadataStore(abc.ABC):
    """Abstract base class for metadata storage backends.

    Defines the interface for inserting, retrieving, deleting, querying,
    and enriching media metadata records.
    """

    @abc.abstractmethod
    def insert(self, record: MediaRecord) -> str:
        """Insert a media record.

        Parameters
        ----------
        record : MediaRecord
            The record to insert. The store sets ``inserted_at`` automatically
            and normalizes ``captured_at`` to UTC.

        Returns
        -------
        str
            The ID of the inserted record.
        """

    @abc.abstractmethod
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

    @abc.abstractmethod
    def delete(self, id: str) -> None:
        """Delete a record by ID.

        Parameters
        ----------
        id : str
            The record ID.

        Raises
        ------
        KeyError
            If no record with the given ID exists.
        """

    @abc.abstractmethod
    def update_enrichment(
        self,
        id: str,
        *,
        labels: list[str] | _UnsetType = UNSET,
        description: str | None | _UnsetType = UNSET,
        embedding: list[float] | None | _UnsetType = UNSET,
        embedding_model: str | None | _UnsetType = UNSET,
    ) -> None:
        """Partially update the enrichment fields of a record.

        Only fields that are not ``UNSET`` are written. Pass ``None`` to
        explicitly clear a field. ``embedding`` and ``embedding_model``
        must be updated together.

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

    @abc.abstractmethod
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
        are combined with AND semantics. ``labels`` uses ANY-match semantics
        (at least one label matches).

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

    @abc.abstractmethod
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
