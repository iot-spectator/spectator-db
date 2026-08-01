# Copyright © 2025 by IoT Spectator. All rights reserved.

import pathlib
import shutil

from spectatordb.storage import storage


class LocalStorage(storage.Storage):
    """Local file system storage backend.

    Provides methods to save, retrieve, delete, and list files in a local directory.

    Parameters
    ----------
    storage_dir : pathlib.Path
        The directory where files will be stored.
        If it does not exist, it will be created.

    Example
    -------
    >>> storage = LocalStorage(pathlib.Path('/path/to/storage'))
    >>> storage.save(pathlib.Path('/path/to/file.txt'))
    >>> storage.retrieve('file.txt', pathlib.Path('/path/to/destination'))
    >>> storage.delete('file.txt')
    >>> files = storage.list_all()  # List all stored files
    """

    def __init__(self, storage_dir: pathlib.Path) -> None:
        self._storage_dir = storage_dir
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        file: pathlib.Path,
        mode: storage.SaveMode = storage.SaveMode.COPY,
        name: str | None = None,
    ) -> None:
        """Save a file to the local storage directory.

        Parameters
        ----------
        file : pathlib.Path
            The full path of the file to be saved.
        mode : SaveMode
            The mode to save the file, either COPY or MOVE.
        name : str | None
            The name to store the file under. If ``None``, the original
            filename is used.

        Raises
        ------
        FileNotFoundError
            If the source file does not exist.
        FileExistsError
            If the file already exists in the storage directory when using COPY mode.
        """
        if not file.exists():
            raise FileNotFoundError(f"Source file {file} does not exist.")
        target_name = name if name is not None else file.name
        target_path = self._storage_dir / target_name
        if mode == storage.SaveMode.MOVE:
            shutil.move(file, target_path)
        else:
            if target_path.exists():
                raise FileExistsError(f"File {target_path} already exists in storage.")
            shutil.copy2(file, target_path)

    def retrieve(self, name: str, dest: pathlib.Path) -> None:
        """Retrieve a file from the local storage directory to a destination path.

        Parameters
        ----------
        name : str
            The name of the file to retrieve.
        dest : pathlib.Path
            The destination path where the file will be copied.

        Raises
        ------
        FileNotFoundError
            If the file does not exist in the storage directory.
        """
        target_path = self._storage_dir / name
        if not target_path.exists():
            raise FileNotFoundError(f"File '{name}' not found.")
        shutil.copy2(target_path, dest)

    def delete(self, name: str) -> None:
        """Delete a file from the local storage directory.

        Parameters
        ----------
        name : str
            The name of the file to delete.
        """
        target_path = self._storage_dir / name
        if target_path.exists():
            target_path.unlink()

    def list_all(self) -> list[pathlib.Path]:
        """List all files stored in the local storage directory.

        Returns
        -------
        list[pathlib.Path]
            A list of pathlib.Path objects representing all files
            in the storage directory.
        """
        return list(self._storage_dir.iterdir())
