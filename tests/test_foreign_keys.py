"""Tests for foreign-key enforcement and on_delete policies."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from tinystore import Database, Field, ForeignKeyError, Model
from tinystore.exceptions import DoesNotExist


class Author(Model):
    id: int | None = Field(default=None, primary_key=True)
    name: str


class Post(Model):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    author_id: int = Field(foreign_key="authors.id", on_delete="CASCADE")


class Comment(Model):
    id: int | None = Field(default=None, primary_key=True)
    body: str
    post_id: int = Field(foreign_key="posts.id", on_delete="CASCADE")
    author_id: int = Field(foreign_key="authors.id", on_delete="RESTRICT")


class Tag(Model):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    alt_author_id: int | None = Field(
        default=None, foreign_key="authors.id", on_delete="SET_NULL"
    )


class Node(Model):
    id: int | None = Field(default=None, primary_key=True)
    parent_id: int | None = Field(
        default=None, foreign_key="nodes.id", on_delete="CASCADE"
    )


@pytest.fixture
def db(db_path: Path) -> Database:
    return Database(db_path)


@pytest.fixture
def populated_db(db: Database) -> Database:
    for cls in (Author, Post, Comment, Tag, Node):
        db.register(cls)
    a = Author(id=1, name="Alice")
    db.insert(a)
    p = Post(id=10, title="Hello", author_id=1)
    db.insert(p)
    return db


# ---- insert validation ----
def test_insert_rejects_missing_parent(db: Database) -> None:
    db.register(Author)
    db.register(Post)
    with pytest.raises(ForeignKeyError):
        db.insert(Post(id=1, title="x", author_id=999))


def test_insert_rejects_unknown_ref_table(db: Database) -> None:
    db.register(Post)
    with pytest.raises(ForeignKeyError):
        db.insert(Post(id=1, title="x", author_id=1))


def test_insert_accepts_valid_fk(populated_db: Database) -> None:
    populated_db.insert(Post(id=11, title="World", author_id=1))


def test_insert_allows_null_fk_when_nullable(populated_db: Database) -> None:
    populated_db.insert(Tag(id=1, name="t"))
    assert populated_db.get(Tag, 1).alt_author_id is None


def test_insert_rejects_null_fk_when_required(db: Database) -> None:
    db.register(Post)
    with pytest.raises(ValidationError):
        db.insert(Post(id=1, title="x"))


# ---- update validation ----
def test_update_rejects_orphaned_fk(populated_db: Database) -> None:
    p = populated_db.get(Post, 10)
    p.author_id = 999
    with pytest.raises(ForeignKeyError):
        populated_db.update(p)


def test_update_accepts_valid_fk(populated_db: Database) -> None:
    populated_db.insert(Author(id=2, name="Bob"))
    p = populated_db.get(Post, 10)
    p.author_id = 2
    populated_db.update(p)
    assert populated_db.get(Post, 10).author_id == 2


# ---- on_delete RESTRICT ----
def test_delete_restrict_blocks_when_referenced(populated_db: Database) -> None:
    populated_db.insert(Comment(id=1, body="hi", post_id=10, author_id=1))
    with pytest.raises(ForeignKeyError):
        populated_db.delete(Author, 1)
    assert populated_db.get(Author, 1) is not None


# ---- on_delete CASCADE ----
def test_delete_cascade_removes_dependents(populated_db: Database) -> None:
    populated_db.delete(Author, 1)
    with pytest.raises(DoesNotExist):
        populated_db.get(Post, 10)


def test_delete_cascade_chains_across_tables(populated_db: Database) -> None:
    populated_db.insert(Comment(id=1, body="hi", post_id=10, author_id=1))
    populated_db.delete(Post, 10)
    with pytest.raises(DoesNotExist):
        populated_db.get(Comment, 1)


# ---- on_delete SET_NULL ----
def test_delete_set_null_clears_fk(populated_db: Database) -> None:
    populated_db.insert(Tag(id=1, name="t", alt_author_id=1))
    populated_db.delete(Author, 1)
    assert populated_db.get(Tag, 1).alt_author_id is None


# ---- self-referential ----
def test_self_referential_cascade(db: Database) -> None:
    db.register(Node)
    db.insert(Node(id=1, parent_id=None))
    db.insert(Node(id=2, parent_id=1))
    db.insert(Node(id=3, parent_id=2))
    db.delete(Node, 1)
    with pytest.raises(DoesNotExist):
        db.get(Node, 2)
    with pytest.raises(DoesNotExist):
        db.get(Node, 3)


def test_self_referential_cycle_terminates(db: Database) -> None:
    db.register(Node)
    for nid in (1, 2, 3):
        db.insert(Node(id=nid, parent_id=None))
    n1 = db.get(Node, 1)
    n1.parent_id = 3
    db.update(n1)
    n2 = db.get(Node, 2)
    n2.parent_id = 1
    db.update(n2)
    n3 = db.get(Node, 3)
    n3.parent_id = 2
    db.update(n3)
    db.delete(Node, 1)
    with pytest.raises(DoesNotExist):
        db.get(Node, 2)
    with pytest.raises(DoesNotExist):
        db.get(Node, 3)


# ---- delete_many cascade ----
def test_delete_many_cascades(populated_db: Database) -> None:
    populated_db.insert(Post(id=11, title="second", author_id=1))
    populated_db.delete_many(Post, [10, 11])
    assert populated_db.count(Post) == 0
