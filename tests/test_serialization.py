"""Tests for serialization round-trips of rich types."""

from __future__ import annotations

import datetime
import uuid

from tinystore import Database, Field, Model
from tinystore.serialization import dumps


def test_roundtrip_datetime_uuid_enum_nested(registered_db: Database, make_user) -> None:
    u = make_user(
        name="Bob",
        email="bob@example.com",
        age=30,
        scores=[1, 2, 3],
        address={"street": "5th Ave", "city": "NYC"},
    )
    registered_db.insert(u)
    loaded = registered_db.get(type(u), u.id)
    assert loaded.name == "Bob"
    assert loaded.age == 30
    assert loaded.scores == [1, 2, 3]
    assert loaded.address is not None
    assert loaded.address.city == "NYC"
    assert isinstance(loaded.uid, uuid.UUID)
    assert isinstance(loaded.created_at, datetime.datetime)
    assert loaded.status.value == "active"


def test_dumps_is_stable_and_sorted() -> None:
    a = dumps({"b": 2, "a": 1, "c": [3, 2, 1]})
    b = dumps({"c": [3, 2, 1], "a": 1, "b": 2})
    assert a == b
    # Keys sorted, ascii-safe off, indented
    assert a.startswith('{\n  "a"')


def test_dumps_ensure_ascii_false() -> None:
    text = dumps({"name": "Réna"})
    assert "Réna" in text  # not escaped


def test_relationship_field_excluded_from_persistence(db: Database) -> None:
    from tinystore.relationships import Relationship

    class Author(Model):
        id: int | None = Field(default=None, primary_key=True)
        name: str

    class Post(Model):
        id: int | None = Field(default=None, primary_key=True)
        title: str
        author_id: int = Field(foreign_key="authors.id")
        author: Author | None = Relationship(foreign_key="author_id")

    db.register(Author)
    db.register(Post)
    a = Author(id=1, name="A")
    db.insert(a)
    p = Post(title="t", author_id=1)
    db.insert(p)
    state = db.storage.read_table("posts")
    row = state["rows"][0]
    assert "author" not in row
    assert row["author_id"] == 1
    assert "__version" in row


def test_version_field_persisted(registered_db: Database, make_user) -> None:
    u = make_user()
    registered_db.insert(u)
    state = registered_db.storage.read_table("users")
    assert state["rows"][0]["__version"] == 1
