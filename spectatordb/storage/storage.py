# Copyright © 2025 by IoT Spectator. All rights reserved.

import abc
import enum
import pathlib

from typing import Optional


class SaveMode(enum.StrEnum):
    """Defines the modes for saving files in storage."""

    COPY = enum.auto()
    MOVE = enum.auto()


class Storage:
    """Abstract base class for storage backends.

    Defines the interface for saving, retrieving, deleting, and listing data objects.
    """

    @abc.abstractmethod
    def save(
        self, file: pathlib.Path, mode: Optional[SaveMode] = SaveMode.COPY
    ) -> None:
        """Save a file into the storage system.

        Parameters
        ----------
        file : pathlib.Path
            The full path of the file to be saved in storage.
        mode: SaveMode
            Copy or move the file to the storage system.
        """
        pass

    @abc.abstractmethod
    def retrieve(self, name: str, dest: pathlib.Path):
        """Retrieve the file to the given destination.

        Parameters
        ----------
        name : str
            The name or identifier of the file to retrieve.

        dest: pathlib.Path
            The destination that the file is retrieved to.
        """
        pass

    @abc.abstractmethod
    def delete(self, name: str) -> None:
        """Delete a file by its name.

        Parameters
        ----------
        name : str
            The name or identifier of the file to delete.
        """
        pass

    @abc.abstractmethod
    def list_all(self) -> list[pathlib.Path]:
        """Return a list of names or identifiers for all stored files."""
        pass
