"""Tests for locking: timeout behavior and concurrent thread access."""

from __future__ import annotations

import threading
import time

import pytest

from tinystore import Database, Model, StaleDataError
from tinystore.exceptions import LockTimeoutError


def test_lock_reentrant_in_same_thread(registered_db: Database, make_user) -> None:
    # Entering db.lock() twice should not deadlock (RLock semantics).
    with registered_db.lock(), registered_db.lock():
        registered_db.insert(make_user(email="a@x.com"))


def test_concurrent_threads_serialize_inserts(db_path, user_model: type[Model], make_user) -> None:
    db = Database(db_path)
    db.register(user_model)
    errors: list[BaseException] = []
    n_threads = 8
    per_thread = 25

    def worker(tid: int) -> None:
        try:
            for i in range(per_thread):
                db.insert(make_user(email=f"t{tid}-{i}@x.com", name=f"t{tid}-{i}"))
        except BaseException as exc:  # pragma: no cover - test reporting
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert db.count(user_model) == n_threads * per_thread
    # IDs should be unique 1..N (no duplicates from a race).
    ids = [u.id for u in db.all(user_model)]
    assert len(set(ids)) == len(ids)
    assert sorted(ids) == list(range(1, n_threads * per_thread + 1))


def test_lock_timeout_raises(db_path) -> None:
    db = Database(db_path, lock_timeout=0.1)
    held = threading.Event()
    release = threading.Event()
    holder_error: list[BaseException] = []

    def holder() -> None:
        try:
            with db.lock(timeout=60):
                held.set()
                release.wait(timeout=5)
        except BaseException as exc:  # pragma: no cover
            holder_error.append(exc)

    t = threading.Thread(target=holder)
    t.start()
    held.wait(timeout=5)
    try:
        with pytest.raises(LockTimeoutError), db.lock(timeout=0.1):
            pass
    finally:
        release.set()
        t.join()
    assert holder_error == []


def test_concurrent_update_optimistic_concurrency_detects_stale(
    db_path, user_model: type[Model], make_user
) -> None:
    # Two threads load the same row, both try to update; exactly one should
    # succeed, the other gets StaleDataError.
    db = Database(db_path)
    db.register(user_model)
    u = db.insert(make_user(email="shared@x.com"))

    results: dict[str, bool] = {"ok": False, "stale": False}
    lock = threading.Lock()

    def updater(name: str, key: str) -> None:
        copy = db.get(user_model, u.id)
        time.sleep(0.05)  # ensure both read before either writes
        copy.name = name
        try:
            db.update(copy)
            with lock:
                results[key] = "ok"
        except StaleDataError:
            with lock:
                results[key] = "stale"

    t1 = threading.Thread(target=updater, args=("A", "ok"))
    t2 = threading.Thread(target=updater, args=("B", "stale"))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # One succeeded, one got stale (order not deterministic -> check values).
    assert sorted(results.values()) == ["ok", "stale"]
