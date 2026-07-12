"""Tests for relationship resolution via db.related()."""

from __future__ import annotations

from pathlib import Path

import pytest

from tinysql import Database, Field, Model
from tinysql.exceptions import RelationshipError
from tinysql.relationships import Relationship


# Many-to-one: Post.author -> Author (FK on the Post side).
class Author(Model):
    id: int | None = Field(default=None, primary_key=True)
    name: str


class Post(Model):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    author_id: int = Field(foreign_key="authors.id", on_delete="CASCADE")
    author: Author | None = Relationship(foreign_key="author_id")


# One-to-many: Order.items -> list[Item] (FK on the Item side).
class Item(Model):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    order_id: int = Field(foreign_key="orders.id", on_delete="CASCADE")


class Order(Model):
    id: int | None = Field(default=None, primary_key=True)
    label: str
    items: list[Item] = Relationship(foreign_key="order_id")


@pytest.fixture
def db(db_path: Path) -> Database:
    return Database(db_path)


def _seed(db: Database) -> None:
    for cls in (Author, Post, Order, Item):
        db.register(cls)
    db.insert(Author(id=1, name="Alice"))
    db.insert(Author(id=2, name="Bob"))
    db.insert(Post(id=10, title="A1", author_id=1))
    db.insert(Post(id=11, title="A2", author_id=1))
    db.insert(Post(id=20, title="B1", author_id=2))
    db.insert(Order(id=1, label="first"))
    db.insert(Item(id=100, name="pen", order_id=1))
    db.insert(Item(id=101, name="pad", order_id=1))


# ---- many-to-one ----
def test_related_many_to_one_returns_parent(db: Database) -> None:
    _seed(db)
    post = db.get(Post, 10)
    author = db.related(post, "author")
    assert isinstance(author, Author)
    assert author.id == 1
    assert author.name == "Alice"


def test_related_many_to_one_tracks_change(db: Database) -> None:
    _seed(db)
    post = db.get(Post, 10)
    post.author_id = 2
    db.update(post)
    assert db.related(post, "author").id == 2


def test_related_unknown_name_raises(db: Database) -> None:
    _seed(db)
    post = db.get(Post, 10)
    with pytest.raises(RelationshipError):
        db.related(post, "nope")


# ---- one-to-many ----
def test_related_one_to_many_returns_list(db: Database) -> None:
    _seed(db)
    order = db.get(Order, 1)
    items = db.related(order, "items")
    assert isinstance(items, list)
    assert {i.id for i in items} == {100, 101}


def test_related_one_to_many_empty(db: Database) -> None:
    _seed(db)
    db.insert(Order(id=2, label="empty"))
    order = db.get(Order, 2)
    assert db.related(order, "items") == []


# ---- relationship field excluded from persistence ----
def test_relationship_field_not_persisted(db: Database) -> None:
    _seed(db)
    row = db.storage.read_table("posts")["rows"][0]
    assert "author" not in row
    order_row = db.storage.read_table("orders")["rows"][0]
    assert "items" not in order_row


# ---- dangling reference is tolerant ----
def test_related_dangling_returns_none(db: Database) -> None:
    _seed(db)
    # Simulate a stale FK by mutating storage directly.
    state = db.storage.read_table("posts")
    state["rows"][0]["author_id"] = 999
    db.storage.write_table("posts", state)
    reloaded = db.get(Post, 10)
    assert db.related(reloaded, "author") is None


# ---- unresolvable one-to-many ----
def test_related_one_to_many_unresolved_raises(db: Database) -> None:
    db.register(Order)
    # Item (which carries the order_id FK) is not registered.
    order = Order(id=1, label="x")
    db.insert(order)
    with pytest.raises(RelationshipError):
        db.related(order, "items")
