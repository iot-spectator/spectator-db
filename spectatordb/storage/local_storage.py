# Copyright © 2025 by IoT Spectator. All rights reserved.

import pathlib

from typing import Optional, override

from spectatordb.storage import SaveMode, Storage


class LocalStorage(Storage):

    def __init__(self, storage_dir: pathlib.Path):
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    @override
    def save(
        self, file: pathlib.Path, mode: Optional[SaveMode] = SaveMode.COPY
    ) -> None:
        pass

    @override
    def retrieve(self, name: str, dest: pathlib.Path) -> None:
        pass

    @override
    def delete(self, name: str) -> None:
        target_path = self.storage_dir / name
        if target_path.exists():
            target_path.unlink()

    @override
    def list_all(self):
        pass
