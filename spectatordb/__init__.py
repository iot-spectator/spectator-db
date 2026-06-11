"""spectator-db — an embeddable media-intelligence store.

Public API
----------
SpectatorDB
    The main facade; orchestrates storage and metadata backends.
MediaRecord
    Data model for a stored media item.
MediaType
    Enum: IMAGE or VIDEO.
ReconcileReport
    Result of a :meth:`SpectatorDB.reconcile` sweep.
UNSET
    Sentinel for :meth:`SpectatorDB.update_enrichment` parameters.
Storage
    Abstract base class for file storage backends.
LocalStorage
    Local filesystem storage backend.
SaveMode
    Enum: COPY or MOVE.
MetadataStore
    Abstract base class for metadata backends.
SQLiteMetadataStore
    SQLite metadata backend (default).
"""

from spectatordb.metadata.metadata_store import MetadataStore
from spectatordb.metadata.sqlite_metadata_store import SQLiteMetadataStore
from spectatordb.models import UNSET, MediaRecord, MediaType, ReconcileReport
from spectatordb.spectatordb import SpectatorDB
from spectatordb.storage.local_storage import LocalStorage
from spectatordb.storage.storage import SaveMode, Storage

__all__ = [
    "SpectatorDB",
    "MediaRecord",
    "MediaType",
    "ReconcileReport",
    "UNSET",
    "Storage",
    "LocalStorage",
    "SaveMode",
    "MetadataStore",
    "SQLiteMetadataStore",
]
