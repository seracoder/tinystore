"""Tests for storage: atomic writes, corruption handling, persistence."""

from __future__ import annotations

import pytest

from tinysql import Database, Field, Model
from tinysql.exceptions import StorageError


def test_table_file_format(registered_db: Database, make_user) -> None:
    registered_db.insert(make_user(email="a@x.com"))
    state = registered_db.storage.read_table("users")
    assert state["version"] == 1
    assert state["next_id"] == 2
    assert len(state["rows"]) == 1
    assert state["rows"][0]["id"] == 1


def test_atomic_write_uses_temp_then_replace(registered_db: Database, make_user) -> None:
    # After a successful write, no .tmp files should remain.
    registered_db.insert(make_user(email="a@x.com"))
    # only the lock file lives at root, not stray temp files in tables/
    temp_files = [p for p in (registered_db.root / "tables").iterdir() if ".tmp" in p.name]
    assert temp_files == []


def test_corrupt_json_raises(db_path, user_model: type[Model], make_user) -> None:
    db = Database(db_path)
    db.register(user_model)
    db.insert(make_user(email="a@x.com"))
    table_path = db_path / "tables" / "users.json"
    # Corrupt the file
    table_path.write_text("{ this is not valid json", encoding="utf-8")
    db2 = Database(db_path)
    with pytest.raises((StorageError, Exception)):
        db2.register(user_model)


def test_malformed_table_missing_rows_raises(db_path) -> None:
    (db_path / "tables").mkdir(parents=True)
    (db_path / "tables" / "things.json").write_text('{"version": 1}', encoding="utf-8")
    db = Database(db_path)

    class Thing(Model):
        id: int | None = Field(default=None, primary_key=True)
        name: str

    with pytest.raises(StorageError):
        db.register(Thing)


def test_data_persists_across_reopen(db_path, user_model: type[Model], make_user) -> None:
    db = Database(db_path)
    db.register(user_model)
    db.insert(make_user(name="Persist", email="p@x.com"))
    del db
    db2 = Database(db_path)
    db2.register(user_model)
    users = db2.all(user_model)
    assert len(users) == 1
    assert users[0].name == "Persist"


def test_journal_dir_created(db_path) -> None:
    Database(db_path)
    assert (db_path / "journal").exists()
    assert (db_path / "tables").exists()
    assert (db_path / "tinysql.lock").exists()


def test_metadata_created_on_first_register(db_path) -> None:
    db = Database(db_path)
    assert not (db_path / "metadata.json").exists()  # lazy

    class Thing(Model):
        id: int | None = Field(default=None, primary_key=True)
        name: str

    db.register(Thing)
    assert (db_path / "metadata.json").exists()


def test_lock_file_existence_is_meaningless(db_path) -> None:
    # Opening and closing leaves the lock file behind; a second open should still work.
    db1 = Database(db_path)
    assert (db_path / "tinysql.lock").exists()
    db2 = Database(db_path)
    # If mere existence were treated as a lock, this would deadlock/timeout.
    assert db2.root == db1.root
