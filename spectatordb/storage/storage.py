# Copyright © 2025 by IoT Spectator. All rights reserved.

import abc
import enum
import pathlib


class SaveMode(enum.StrEnum):
    """Defines the modes for saving files in storage."""

    COPY = enum.auto()
    MOVE = enum.auto()


class Storage(abc.ABC):
    """Abstract base class for storage backends.

    Defines the interface for saving, retrieving, deleting, and listing data objects.
    """

    @abc.abstractmethod
    def save(
        self,
        file: pathlib.Path,
        mode: SaveMode = SaveMode.COPY,
        name: str | None = None,
    ) -> None:
        """Save a file into the storage system.

        Parameters
        ----------
        file : pathlib.Path
            The full path of the file to be saved in storage.
        mode : SaveMode
            Copy or move the file to the storage system.
        name : str | None
            The name to store the file under. If ``None``, the original
            filename is used.
        """

    @abc.abstractmethod
    def retrieve(self, name: str, dest: pathlib.Path) -> None:
        """Retrieve the file to the given destination.

        Parameters
        ----------
        name : str
            The name or identifier of the file to retrieve.
        dest : pathlib.Path
            The destination that the file is retrieved to.

        Raises
        ------
        FileNotFoundError
            If the file does not exist in storage.
        """

    @abc.abstractmethod
    def delete(self, name: str) -> None:
        """Delete a file by its name.

        Parameters
        ----------
        name : str
            The name or identifier of the file to delete.
        """

    @abc.abstractmethod
    def list_all(self) -> list[pathlib.Path]:
        """Return a list of paths for all stored files."""
