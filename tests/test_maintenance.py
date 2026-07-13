"""Tests for maintenance: check() and backup()."""

from __future__ import annotations

from pathlib import Path

import pytest

from tinystore import Database
from tinystore.exceptions import DoesNotExist


def test_check_clean_db_returns_no_problems(registered_db: Database, make_user) -> None:
    registered_db.insert(make_user(email="a@x.com"))
    assert registered_db.check() == []


def test_check_detects_duplicate_pk(registered_db: Database, make_user) -> None:
    registered_db.insert(make_user(email="a@x.com"))
    # Manually inject a duplicate primary key.
    state = registered_db.storage.read_table("users")
    state["rows"].append(dict(state["rows"][0]))  # same id=1
    registered_db.storage.write_table("users", state)
    problems = registered_db.check()
    assert any("duplicate primary key" in p for p in problems)


def test_check_detects_bad_next_id(registered_db: Database, make_user) -> None:
    registered_db.insert(make_user(email="a@x.com"))
    state = registered_db.storage.read_table("users")
    state["next_id"] = 1  # <= max id
    registered_db.storage.write_table("users", state)
    problems = registered_db.check()
    assert any("next_id" in p for p in problems)


def test_backup_creates_readable_copy(
    registered_db: Database, make_user, tmp_path: Path, user_model: type
) -> None:
    registered_db.insert(make_user(email="a@x.com"))
    registered_db.insert(make_user(email="b@x.com"))
    target = tmp_path / "backup"
    result = registered_db.backup(target)
    assert result == target
    assert (target / "metadata.json").exists()
    assert (target / "tables" / "users.json").exists()

    # The backup should be independently readable.
    db2 = Database(target)
    db2.register(user_model)
    assert db2.count(user_model) == 2


def test_backup_excludes_lock_and_journal(registered_db: Database, tmp_path: Path) -> None:
    target = tmp_path / "bk"
    registered_db.backup(target)
    assert not (target / "tinystore.lock").exists()
    assert not (target / "journal").exists()


def test_get_by_returns_one(registered_db: Database, make_user, user_model: type) -> None:
    registered_db.insert(make_user(email="a@x.com"))
    u = registered_db.get_by(user_model, "email", "a@x.com")
    assert u.email == "a@x.com"
    with pytest.raises(DoesNotExist):
        registered_db.get_by(user_model, "email", "missing@x.com")
