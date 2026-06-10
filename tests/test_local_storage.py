import pytest

from spectatordb.storage.storage import SaveMode
from spectatordb.storage.local_storage import LocalStorage


def test_save_and_list_all(tmp_path):
    storage_dir = tmp_path / "storage"
    storage = LocalStorage(storage_dir=storage_dir)
    file_path = tmp_path / "testfile.mp4"
    file_path.write_text("hello world")
    storage.save(file=file_path, mode=SaveMode.COPY)
    stored_files = storage.list_all()
    assert any(f.name == "testfile.mp4" for f in stored_files)
    assert file_path.exists()


def test_save_move(tmp_path):
    storage_dir = tmp_path / "storage"
    storage = LocalStorage(storage_dir=storage_dir)
    file_path = tmp_path / "movefile.jpg"
    file_path.write_text("move me")
    storage.save(file_path, mode=SaveMode.MOVE)
    stored_files = storage.list_all()
    assert any(f.name == "movefile.jpg" for f in stored_files)
    assert not file_path.exists()


def test_save_with_custom_name(tmp_path):
    storage_dir = tmp_path / "storage"
    storage = LocalStorage(storage_dir=storage_dir)
    file_path = tmp_path / "original.jpg"
    file_path.write_text("data")
    storage.save(file_path, mode=SaveMode.COPY, name="custom-name.jpg")
    stored_files = storage.list_all()
    assert any(f.name == "custom-name.jpg" for f in stored_files)
    assert not any(f.name == "original.jpg" for f in stored_files)


def test_save_duplicate_raises(tmp_path):
    storage_dir = tmp_path / "storage"
    storage = LocalStorage(storage_dir=storage_dir)
    file_path = tmp_path / "dup.txt"
    file_path.write_text("dup")
    storage.save(file_path, mode=SaveMode.COPY)
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
    assert len(storage.list_all()) == 1
    storage.delete("delme.txt")
    assert len(storage.list_all()) == 0


def test_delete_nonexistent(tmp_path):
    storage = LocalStorage(tmp_path)
    storage.delete("nope.txt")
