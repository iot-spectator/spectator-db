"""Data models for spectator-db."""

import enum
import uuid

from dataclasses import dataclass, field
from datetime import datetime


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
        When the media was captured, provided by the caller.
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
