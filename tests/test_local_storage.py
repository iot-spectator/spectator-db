import pytest

from spectatordb.storage.storage import SaveMode
from spectatordb.storage.local_storage import LocalStorage


def test_save_and_list_all(tmp_path):
    storage_dir = tmp_path / "storage"
    storage = LocalStorage(storage_dir=storage_dir)
    # Create a temp file to save
    file_path = tmp_path / "testfile.mp4"
    file_path.write_text("hello world")
    storage.save(file=file_path, mode=SaveMode.COPY)
    # File should exist in storage dir
    stored_files = storage.list_all()
    assert any(f.name == "testfile.mp4" for f in stored_files)
    # Original file should still exist (COPY)
    assert file_path.exists()


def test_save_move(tmp_path):
    storage_dir = tmp_path / "storage"
    storage = LocalStorage(storage_dir=storage_dir)
    file_path = tmp_path / "movefile.jpg"
    file_path.write_text("move me")
    storage.save(file_path, mode=SaveMode.MOVE)
    # File should exist in storage dir
    stored_files = storage.list_all()
    assert any(f.name == "movefile.jpg" for f in stored_files)
    # Original file should be gone
    assert not file_path.exists()


def test_save_duplicate_raises(tmp_path):
    storage_dir = tmp_path / "storage"
    storage = LocalStorage(storage_dir=storage_dir)
    file_path = tmp_path / "dup.txt"
    file_path.write_text("dup")
    storage.save(file_path, mode=SaveMode.COPY)
    # Try to save again, should raise
    file_path2 = tmp_path / "dup.txt"
    file_path2.write_text("dup2")
    with pytest.raises(FileExistsError):
        storage.save(file_path2, mode=SaveMode.COPY)


def test_retrieve(tmp_path):
    storage_dir = tmp_path / "storage"
    storage = LocalStorage(storage_dir=storage_dir)
    file_path = tmp_path / "getme.txt"
    file_path.write_text("get me")
    storage.save(file_path, mode=SaveMode.COPY)
    dest = tmp_path / "retrieved.txt"
    storage.retrieve("getme.txt", dest)
    assert dest.exists()
    assert dest.read_text() == "get me"


def test_retrieve_missing_raises(tmp_path):
    storage = LocalStorage(tmp_path)
    dest = tmp_path / "notfound.txt"
    with pytest.raises(FileNotFoundError):
        storage.retrieve("missing.txt", dest)


def test_delete(tmp_path):
    storage_dir = tmp_path / "storage"
    storage = LocalStorage(storage_dir=storage_dir)
    file_path = tmp_path / "delme.txt"
    file_path.write_text("bye")
    storage.save(file_path, mode=SaveMode.COPY)

    stored_files = storage.list_all()
    assert len(stored_files) == 1

    storage.delete("delme.txt")
    stored_files = storage.list_all()
    assert len(stored_files) == 0


def test_delete_nonexistent(tmp_path):
    storage = LocalStorage(tmp_path)
    # Should not raise
    storage.delete("nope.txt")
