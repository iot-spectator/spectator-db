# Copyright © 2025 by IoT Spectator. All rights reserved.

import pathlib
import shutil

from typing import Optional, override

from spectatordb.storage import SaveMode, Storage


class LocalStorage(Storage):

    def __init__(self, storage_dir: pathlib.Path):
        self._storage_dir = storage_dir
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    @override
    def save(
        self, file: pathlib.Path, mode: Optional[SaveMode] = SaveMode.COPY
    ) -> None:
        if not file.exists():
            raise FileNotFoundError(f"Source file {file} does not exist.")
        target_path = self._storage_dir / file.name
        if mode == SaveMode.MOVE:
            shutil.move(file, target_path)
        else:
            if target_path.exists():
                raise FileExistsError(f"File {target_path} already exists in storage.")
            shutil.copy2(file, target_path)

    @override
    def retrieve(self, name: str, dest: pathlib.Path) -> None:
        target_path = self._storage_dir / name
        if not target_path.exists():
            raise FileNotFoundError(f"Video '{name}' not found.")
        shutil.copy2(target_path, dest)

    @override
    def delete(self, name: str) -> None:
        target_path = self._storage_dir / name
        if target_path.exists():
            target_path.unlink()

    @override
    def list_all(self) -> list[pathlib.Path]:
        return list(self._storage_dir.iterdir())
