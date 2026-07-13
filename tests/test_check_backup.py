"""Tests for db.check() integrity validation and db.backup() snapshots."""

from __future__ import annotations

from pathlib import Path

import pytest

from tinysql import Database, Field, Model


class User(Model):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    email: str = Field(unique=True)


class Post(Model):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    author_id: int = Field(foreign_key="users.id", on_delete="CASCADE")


@pytest.fixture
def db(db_path: Path) -> Database:
    d = Database(db_path)
    d.register(User)
    d.register(Post)
    return d


# ---- check() ----
def test_check_clean_db_passes(db: Database) -> None:
    db.insert(User(id=1, name="Alice", email="a@x.com"))
    db.insert(Post(id=10, title="Hi", author_id=1))
    assert db.check() == []


def test_check_detects_duplicate_pk(db: Database, db_path: Path) -> None:
    db.insert(User(id=1, name="Alice", email="a@x.com"))
    # Tamper: inject a duplicate primary key directly into the table file.
    state = db.storage.read_table("users")
    state["rows"].append(state["rows"][0])
    db.storage.write_table("users", state)
    problems = db.check()
    assert any("duplicate primary key" in p for p in problems)


def test_check_detects_stale_next_id(db: Database) -> None:
    db.insert(User(id=1, name="Alice", email="a@x.com"))
    db.insert(User(id=2, name="Bob", email="b@x.com"))
    # Tamper: set next_id below the max id.
    state = db.storage.read_table("users")
    state["next_id"] = 1
    db.storage.write_table("users", state)
    problems = db.check()
    assert any("next_id" in p for p in problems)


def test_check_detects_broken_fk(db: Database) -> None:
    db.insert(User(id=1, name="Alice", email="a@x.com"))
    db.insert(Post(id=10, title="Hi", author_id=1))
    # Tamper: point the post at a non-existent user.
    state = db.storage.read_table("posts")
    state["rows"][0]["author_id"] = 999
    db.storage.write_table("posts", state)
    problems = db.check()
    assert any("missing users.id" in p for p in problems)


def test_check_passes_when_fk_is_null(db: Database) -> None:
    # A null FK should not be flagged.
    db.insert(User(id=1, name="Alice", email="a@x.com"))
    db.insert(Post(id=10, title="Hi", author_id=1))
    state = db.storage.read_table("posts")
    state["rows"][0]["author_id"] = None
    db.storage.write_table("posts", state)
    assert db.check() == []


# ---- backup() ----
def test_backup_creates_consistent_snapshot(db: Database, db_path: Path) -> None:
    db.insert(User(id=1, name="Alice", email="a@x.com"))
    db.insert(User(id=2, name="Bob", email="b@x.com"))
    db.insert(Post(id=10, title="Hi", author_id=1))

    backup_dir = db_path / "backup"
    db.backup(backup_dir)

    # Open the backup read-only and verify data matches.
    bak = Database(backup_dir)
    bak.register(User)
    bak.register(Post)
    assert bak.count(User) == 2
    assert bak.count(Post) == 1
    assert {u.name for u in bak.all(User)} == {"Alice", "Bob"}


def test_backup_excludes_lock_and_journals(db: Database, db_path: Path) -> None:
    db.insert(User(id=1, name="Alice", email="a@x.com"))
    backup_dir = db_path / "backup"
    db.backup(backup_dir)
    # No lock file in the backup.
    assert not (backup_dir / "tinysql.lock").exists()
    # No journal directory.
    assert not (backup_dir / "journal").exists()


def test_backup_is_a_point_in_time_copy(db: Database, db_path: Path) -> None:
    db.insert(User(id=1, name="Alice", email="a@x.com"))
    backup_dir = db_path / "backup"
    db.backup(backup_dir)

    # Mutate the live database after the backup.
    db.insert(User(id=2, name="Bob", email="b@x.com"))

    bak = Database(backup_dir)
    bak.register(User)
    assert bak.count(User) == 1  # backup frozen at backup time
    assert db.count(User) == 2
