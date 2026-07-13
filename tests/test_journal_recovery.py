"""Tests for the write-ahead journal, crash recovery, and transactional constraints."""

from __future__ import annotations

from pathlib import Path

import pytest

from tinystore import Database, Field, ForeignKeyError, Model
from tinystore.exceptions import UniqueConstraintError
from tinystore.serialization import dumps


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


# ---- journal lifecycle ----
def test_no_journal_left_after_commit(db: Database) -> None:
    with db.transaction():
        db.insert(User(id=1, name="Alice", email="a@x.com"))
    assert db.storage.list_journals() == []


def test_no_journal_written_on_rollback(db: Database) -> None:
    with pytest.raises(RuntimeError), db.transaction():
        db.insert(User(id=1, name="Alice", email="a@x.com"))
        raise RuntimeError("boom")
    assert db.storage.list_journals() == []
    assert db.count(User) == 0


def test_multi_table_transaction_commits_all(db: Database) -> None:
    with db.transaction():
        db.insert(User(id=1, name="Alice", email="a@x.com"))
        db.insert(Post(id=10, title="Hi", author_id=1))
    assert db.count(User) == 1
    assert db.count(Post) == 1
    assert db.storage.list_journals() == []


# ---- crash recovery ----
def test_recovery_replays_leftover_journal(db_path: Path) -> None:
    # Open, register, then simulate a committed-but-unapplied transaction by
    # writing a journal directly (no table files written for the new rows).
    d = Database(db_path)
    d.register(User)
    journal = {
        "txid": "0000000001",
        "tables": {
            "users": {
                "next_id": 3,
                "rows": [
                    {"id": 1, "name": "Alice", "email": "a@x.com", "__version": 1},
                    {"id": 2, "name": "Bob", "email": "b@x.com", "__version": 1},
                ],
                "version": 1,
            }
        },
    }
    (d.storage.journal_dir / "0000000001.json").write_text(dumps(journal), encoding="utf-8")
    # Reopen -> recovery should replay the journal.
    d2 = Database(db_path)
    d2.register(User)
    assert d2.count(User) == 2
    assert {u.name for u in d2.all(User)} == {"Alice", "Bob"}
    assert d2.storage.list_journals() == []


def test_recovery_partial_apply_finishes(db_path: Path) -> None:
    # Simulate a crash mid-apply: journal lists two tables, but only one was
    # written before the "crash". Recovery must finish the second.
    d = Database(db_path)
    d.register(User)
    d.register(Post)
    journal = {
        "txid": "0000000007",
        "tables": {
            "users": {
                "next_id": 2,
                "rows": [
                    {"id": 1, "name": "Alice", "email": "a@x.com", "__version": 1},
                ],
                "version": 1,
            },
            "posts": {
                "next_id": 11,
                "rows": [
                    {"id": 10, "title": "Hi", "author_id": 1, "__version": 1},
                ],
                "version": 1,
            },
        },
    }
    # Apply ONLY users (as if the process died before writing posts).
    d.storage.write_table("users", journal["tables"]["users"])
    # Leave the journal on disk.
    (d.storage.journal_dir / "0000000007.json").write_text(dumps(journal), encoding="utf-8")

    d2 = Database(db_path)
    d2.register(User)
    d2.register(Post)
    assert d2.count(User) == 1
    assert d2.count(Post) == 1
    assert d2.get(Post, 10).author_id == 1
    assert d2.storage.list_journals() == []


def test_recovery_multiple_journals_in_order(db_path: Path) -> None:
    d = Database(db_path)
    d.register(User)
    # Two journals: tx 1 then tx 2. Recovery applies in sorted order, so tx 2
    # (the newer full-table state) wins.
    for txid, name in (("0000000001", "Alice"), ("0000000002", "Bob")):
        journal = {
            "txid": txid,
            "tables": {
                "users": {
                    "next_id": 2,
                    "rows": [
                        {"id": 1, "name": name, "email": f"{name.lower()}@x.com", "__version": 1},
                    ],
                    "version": 1,
                }
            },
        }
        (d.storage.journal_dir / f"{txid}.json").write_text(dumps(journal), encoding="utf-8")
    d2 = Database(db_path)
    d2.register(User)
    users = d2.all(User)
    assert len(users) == 1
    assert users[0].name == "Bob"


# ---- transactional constraints ----
def test_transaction_unique_violation_rolls_back(db: Database) -> None:
    db.insert(User(id=1, name="Alice", email="dup@x.com"))
    with pytest.raises(UniqueConstraintError), db.transaction():
        db.insert(User(id=2, name="Bob", email="dup@x.com"))
    # Nothing from the failed transaction persisted.
    assert db.count(User) == 1
    assert db.storage.list_journals() == []


def test_transaction_fk_violation_rolls_back(db: Database) -> None:
    with pytest.raises(ForeignKeyError), db.transaction():
        db.insert(Post(id=10, title="orphan", author_id=999))
    assert db.count(Post) == 0


def test_transactional_cascade_is_atomic(db: Database) -> None:
    db.insert(User(id=1, name="Alice", email="a@x.com"))
    db.insert(Post(id=10, title="Hi", author_id=1))
    db.insert(Post(id=11, title="Bye", author_id=1))
    with db.transaction():
        db.delete(User, 1)
    # Both posts cascade-deleted within the same atomic transaction.
    assert db.count(User) == 0
    assert db.count(Post) == 0


def test_implicit_transaction_uses_journal(db: Database) -> None:
    # A single op (no explicit transaction) still goes through the journal path.
    # We can't observe the journal mid-op, but we can confirm the result is
    # durably written and no journal is left dangling.
    db.insert(User(id=1, name="Alice", email="a@x.com"))
    assert db.storage.list_journals() == []
    # Reopen to confirm durability.
    d2 = Database(db.root)
    d2.register(User)
    assert d2.count(User) == 1
