"""Tests for transactions: commit, rollback, nested rejection."""

from __future__ import annotations

import pytest

from tinysql import Database, Model
from tinysql.exceptions import TransactionError


def test_transaction_commit_persists(
    registered_db: Database, make_user, user_model: type[Model]
) -> None:
    with registered_db.transaction():
        registered_db.insert(make_user(email="a@x.com"))
        registered_db.insert(make_user(email="b@x.com"))
    assert registered_db.count(user_model) == 2


def test_transaction_rollback_discards(
    registered_db: Database, make_user, user_model: type[Model]
) -> None:
    registered_db.insert(make_user(email="keep@x.com"))
    with pytest.raises(RuntimeError), registered_db.transaction():
        registered_db.insert(make_user(email="temp@x.com"))
        raise RuntimeError("boom")
    assert registered_db.count(user_model) == 1


def test_transaction_rollback_leaves_disk_untouched(registered_db: Database, make_user) -> None:
    with pytest.raises(RuntimeError), registered_db.transaction():
        registered_db.insert(make_user(email="x@x.com"))
        raise RuntimeError("boom")
    # The table file should contain zero rows.
    state = registered_db.storage.read_table("users")
    assert state["rows"] == []


def test_nested_transactions_rejected(registered_db: Database) -> None:
    with (
        registered_db.transaction(),
        pytest.raises(TransactionError),
        registered_db.transaction(),
    ):
        pass


def test_transaction_reads_see_buffered_writes(
    registered_db: Database, make_user, user_model: type[Model]
) -> None:
    with registered_db.transaction():
        registered_db.insert(make_user(email="buf@x.com"))
        assert registered_db.count(user_model) == 1


def test_transaction_isolation_from_other_instances(tmp_path) -> None:
    # An open transaction holds the database-wide lock, so a second Database
    # instance on the same directory cannot read until the transaction commits.
    import threading

    from tests.conftest import User
    from tinysql.exceptions import LockTimeoutError

    # Register on both instances first (no contention yet).
    db = Database(tmp_path / "iso")
    db.register(User)
    db2 = Database(tmp_path / "iso", lock_timeout=0.3)
    db2.register(User)

    ready = threading.Event()
    proceed = threading.Event()
    holder_done = threading.Event()

    def holder() -> None:
        with db.transaction():
            db.insert(User(name="A", email="a@x.com"))
            ready.set()
            proceed.wait(timeout=10)
        holder_done.set()

    t = threading.Thread(target=holder)
    t.start()
    assert ready.wait(timeout=10)

    # While the transaction is open, db2 cannot acquire the lock.
    with pytest.raises(LockTimeoutError):
        db2.count(User)

    # Let the holder commit.
    proceed.set()
    assert holder_done.wait(timeout=10)
    t.join()

    # Now the lock is free; the committed row is visible.
    assert db2.count(User) == 1
