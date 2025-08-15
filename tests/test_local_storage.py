import pytest

from spectatordb.storage.local_storage import LocalStorage
from spectatordb.storage import SaveMode


def test_save_and_list_all(tmp_path):
    storage = LocalStorage(tmp_path)
    # Create a temp file to save
    file_path = tmp_path / "testfile.txt"
    file_path.write_text("hello world")
    # Save file
    storage.save(file_path, mode=SaveMode.COPY)
    # File should exist in storage dir
    stored_files = storage.list_all()
    assert any(f.name == "testfile.txt" for f in stored_files)
    # Original file should still exist (COPY)
    assert file_path.exists()


def test_save_move(tmp_path):
    storage = LocalStorage(tmp_path)
    file_path = tmp_path / "movefile.txt"
    file_path.write_text("move me")
    storage.save(file_path, mode=SaveMode.MOVE)
    # File should exist in storage dir
    assert (tmp_path / "movefile.txt").exists()
    # Original file should be gone
    assert not file_path.exists()


def test_save_duplicate_raises(tmp_path):
    storage = LocalStorage(tmp_path)
    file_path = tmp_path / "dup.txt"
    file_path.write_text("dup")
    storage.save(file_path, mode=SaveMode.COPY)
    # Try to save again, should raise
    file_path2 = tmp_path / "dup.txt"
    file_path2.write_text("dup2")
    with pytest.raises(FileExistsError):
        storage.save(file_path2, mode=SaveMode.COPY)


def test_retrieve(tmp_path):
    storage = LocalStorage(tmp_path)
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
    storage = LocalStorage(tmp_path)
    file_path = tmp_path / "delme.txt"
    file_path.write_text("bye")
    storage.save(file_path, mode=SaveMode.COPY)
    storage.delete("delme.txt")
    assert not (tmp_path / "delme.txt").exists()


def test_delete_nonexistent(tmp_path):
    storage = LocalStorage(tmp_path)
    # Should not raise
    storage.delete("nope.txt")
