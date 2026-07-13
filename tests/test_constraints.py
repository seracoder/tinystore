"""Tests for constraints: unique, optimistic concurrency."""

from __future__ import annotations

import pytest

from tinystore import Database, Field, Model
from tinystore.exceptions import StaleDataError, UniqueConstraintError


def test_unique_violation_on_insert(registered_db: Database, make_user) -> None:
    registered_db.insert(make_user(email="dup@x.com"))
    with pytest.raises(UniqueConstraintError):
        registered_db.insert(make_user(email="dup@x.com"))


def test_unique_violation_on_update(registered_db: Database, make_user) -> None:
    registered_db.insert(make_user(email="a@x.com"))
    u2 = registered_db.insert(make_user(email="b@x.com"))
    u2.email = "a@x.com"
    with pytest.raises(UniqueConstraintError):
        registered_db.update(u2)


def test_unique_update_to_same_own_value_ok(registered_db: Database, make_user) -> None:
    u = registered_db.insert(make_user(email="a@x.com"))
    u.name = "renamed"
    registered_db.update(u)  # email unchanged for same row, should succeed
    assert registered_db.get(type(u), u.id).name == "renamed"


def test_unique_allows_null_duplicates(registered_db: Database, make_user) -> None:
    class Opt(Model):
        id: int | None = Field(default=None, primary_key=True)
        nickname: str | None = Field(default=None, unique=True)

    registered_db.register(Opt)
    registered_db.insert(Opt())
    registered_db.insert(Opt())  # both nulls, allowed


def test_optimistic_concurrency_stale_raises(registered_db: Database, make_user) -> None:
    u = registered_db.insert(make_user(email="a@x.com"))
    copy1 = registered_db.get(type(u), u.id)
    copy2 = registered_db.get(type(u), u.id)
    copy1.name = "first"
    registered_db.update(copy1)
    copy2.name = "second"
    with pytest.raises(StaleDataError):
        registered_db.update(copy2)


def test_optimistic_concurrency_disabled(db_path, user_model, make_user) -> None:
    db = Database(db_path, optimistic_concurrency=False)
    db.register(user_model)
    u = db.insert(make_user(email="a@x.com"))
    c1 = db.get(type(u), u.id)
    c2 = db.get(type(u), u.id)
    db.update(c1)
    c2.name = "overwrites"
    db.update(c2)  # no error; last-write-wins
    assert db.get(type(u), u.id).name == "overwrites"


def test_version_increments_on_update(registered_db: Database, make_user) -> None:
    u = registered_db.insert(make_user(email="a@x.com"))
    assert u._tinystore_version == 1
    u.name = "x"
    registered_db.update(u)
    assert u._tinystore_version == 2
    assert registered_db.get(type(u), u.id)._tinystore_version == 2


def test_duplicate_explicit_pk_rejected(registered_db: Database, make_user) -> None:
    u = make_user(email="a@x.com")
    u.id = 5
    registered_db.insert(u)
    u2 = make_user(email="b@x.com")
    u2.id = 5
    with pytest.raises(UniqueConstraintError):
        registered_db.insert(u2)
