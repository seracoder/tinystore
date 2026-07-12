"""Tests for CRUD operations and auto-increment."""

from __future__ import annotations

import pytest

from tinysql import Database, Model
from tinysql.exceptions import DoesNotExist


def test_insert_assigns_autoincrement(registered_db: Database, make_user) -> None:
    u1 = make_user(email="a@x.com")
    u2 = make_user(email="b@x.com")
    registered_db.insert(u1)
    registered_db.insert(u2)
    assert u1.id == 1
    assert u2.id == 2


def test_insert_with_explicit_id(registered_db: Database, make_user) -> None:
    u = make_user(email="a@x.com")
    u.id = 100
    registered_db.insert(u)
    assert registered_db.get(type(u), 100).name == "Alice"


def test_get_missing_raises(registered_db: Database, user_model: type[Model]) -> None:
    with pytest.raises(DoesNotExist):
        registered_db.get(user_model, 999)


def test_all_returns_typed_instances(registered_db: Database, make_user, user_model) -> None:
    registered_db.insert(make_user(email="a@x.com"))
    registered_db.insert(make_user(email="b@x.com"))
    result = registered_db.all(user_model)
    assert len(result) == 2
    assert all(isinstance(x, user_model) for x in result)


def test_update_modifies_row(registered_db: Database, make_user) -> None:
    u = make_user(email="a@x.com")
    registered_db.insert(u)
    u.name = "Changed"
    registered_db.update(u)
    loaded = registered_db.get(type(u), u.id)
    assert loaded.name == "Changed"


def test_save_insert_then_update(registered_db: Database, make_user) -> None:
    u = make_user(email="a@x.com")
    registered_db.save(u)
    assert u.id == 1
    u.name = "Saved"
    registered_db.save(u)
    assert registered_db.get(type(u), 1).name == "Saved"


def test_delete_by_pk(registered_db: Database, make_user, user_model) -> None:
    u = make_user(email="a@x.com")
    registered_db.insert(u)
    assert registered_db.delete(user_model, u.id) == 1
    with pytest.raises(DoesNotExist):
        registered_db.get(user_model, u.id)


def test_delete_by_instance(registered_db: Database, make_user, user_model) -> None:
    u = make_user(email="a@x.com")
    registered_db.insert(u)
    registered_db.delete(u)
    assert registered_db.count(user_model) == 0


def test_count(registered_db: Database, make_user, user_model) -> None:
    for i in range(5):
        registered_db.insert(make_user(email=f"u{i}@x.com"))
    assert registered_db.count(user_model) == 5


def test_insert_many(registered_db: Database, make_user, user_model) -> None:
    users = [make_user(email=f"m{i}@x.com") for i in range(4)]
    result = registered_db.insert_many(users)
    assert [u.id for u in result] == [1, 2, 3, 4]
    assert registered_db.count(user_model) == 4


def test_update_many(registered_db: Database, make_user) -> None:
    users = [make_user(email=f"m{i}@x.com") for i in range(3)]
    registered_db.insert_many(users)
    for u in users:
        u.name = "updated"
    registered_db.update_many(users)
    loaded = registered_db.all(type(users[0]))
    assert all(x.name == "updated" for x in loaded)


def test_delete_many(registered_db: Database, make_user, user_model) -> None:
    users = [make_user(email=f"m{i}@x.com") for i in range(5)]
    registered_db.insert_many(users)
    n = registered_db.delete_many(user_model, [users[0].id, users[1].id])
    assert n == 2
    assert registered_db.count(user_model) == 3


def test_table_facade(registered_db: Database, make_user, user_model) -> None:
    tbl = registered_db.table(user_model)
    u = make_user(email="t@x.com")
    tbl.insert(u)
    assert tbl.get(u.id).name == "Alice"
    assert tbl.count() == 1


def test_autoincrement_persisted_across_reopen(db_path, user_model, make_user) -> None:
    db = Database(db_path)
    db.register(user_model)
    db.insert(make_user(email="a@x.com"))
    db.insert(make_user(email="b@x.com"))
    del db
    db2 = Database(db_path)
    db2.register(user_model)
    u3 = make_user(email="c@x.com")
    db2.insert(u3)
    assert u3.id == 3
