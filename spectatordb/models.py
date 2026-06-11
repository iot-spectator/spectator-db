"""Data models for spectator-db."""

import enum
import uuid

from dataclasses import dataclass, field
from datetime import datetime
from typing import Final


class _UnsetType:
    """Sentinel type for unset parameters in update_enrichment."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "UNSET"


UNSET: Final[_UnsetType] = _UnsetType()


class MediaType(enum.StrEnum):
    """Defines the types of media that can be stored in the database."""

    VIDEO = enum.auto()
    IMAGE = enum.auto()


@dataclass
class MediaRecord:
    """A record of a stored media file.

    Parameters
    ----------
    media_type : MediaType
        Type of media (IMAGE or VIDEO).
    captured_at : datetime
        When the media was captured. Normalized to tz-aware UTC on write.
    format : str
        File extension, e.g. ``jpg``, ``avi``.
    size : int
        File size in bytes.
    id : str
        UUID, auto-generated on creation.
    inserted_at : datetime | None
        When stored, set automatically by the metadata store.
    duration : float | None
        Duration in seconds; video only.
    device_id : str | None
        Which device captured this media.
    labels : list[str]
        Semantic labels, e.g. ``["person", "car"]``.
    description : str | None
        Text summary of the media content.
    embedding : list[float] | None
        Vector embedding for semantic search.
    embedding_model : str | None
        Identity of the model that produced the embedding.
    embedding_dim : int | None
        Dimension of the embedding vector; enforced on write.
    content_hash : str | None
        SHA-256 content hash for optional deduplication.
    """

    media_type: MediaType
    captured_at: datetime
    format: str
    size: int
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    inserted_at: datetime | None = None
    duration: float | None = None
    device_id: str | None = None
    labels: list[str] = field(default_factory=list)
    description: str | None = None
    embedding: list[float] | None = None
    embedding_model: str | None = None
    embedding_dim: int | None = None
    content_hash: str | None = None

    def __post_init__(self) -> None:
        """Validate embedding field consistency."""
        embedding_fields = (self.embedding, self.embedding_model, self.embedding_dim)
        set_count = sum(f is not None for f in embedding_fields)
        if 0 < set_count < 3:
            raise ValueError(
                "embedding, embedding_model, and embedding_dim must all be"
                " set together or all be None"
            )
        if self.embedding is not None and len(self.embedding) != self.embedding_dim:
            raise ValueError(
                f"embedding length {len(self.embedding)} does not match"
                f" embedding_dim {self.embedding_dim}"
            )


@dataclass
class ReconcileReport:
    """Report from a reconcile sweep.

    Parameters
    ----------
    orphaned_files : list[str]
        File names present in storage with no matching metadata row.
    dangling_rows : list[str]
        Record IDs in metadata with no backing file in storage.
    deleted_files : int
        Number of orphaned files deleted.
    deleted_rows : int
        Number of dangling metadata rows deleted.
    """

    orphaned_files: list[str] = field(default_factory=list)
    dangling_rows: list[str] = field(default_factory=list)
    deleted_files: int = 0
    deleted_rows: int = 0
