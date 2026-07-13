"""Tests for in-memory INNER and LEFT joins."""

from __future__ import annotations

from pathlib import Path

import pytest

from tinystore import Database, Field, Model
from tinystore.exceptions import MultipleObjectsReturned, QueryError
from tinystore.query.joins import Row


class User(Model):
    id: int | None = Field(default=None, primary_key=True)
    name: str


class Post(Model):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    author_id: int | None = Field(default=None, foreign_key="users.id", on_delete="CASCADE")


class Comment(Model):
    id: int | None = Field(default=None, primary_key=True)
    body: str
    post_id: int = Field(foreign_key="posts.id", on_delete="CASCADE")


@pytest.fixture
def db(db_path: Path) -> Database:
    db = Database(db_path)
    for cls in (User, Post, Comment):
        db.register(cls)
    db.insert(User(id=1, name="Alice"))
    db.insert(User(id=2, name="Bob"))
    db.insert(Post(id=10, title="A1", author_id=1))
    db.insert(Post(id=11, title="A2", author_id=1))
    db.insert(Post(id=20, title="B1", author_id=2))
    db.insert(Post(id=21, title="orphan", author_id=None))
    db.insert(Comment(id=100, body="c1", post_id=10))
    db.insert(Comment(id=101, body="c2", post_id=10))
    return db


# ---- INNER join ----
def test_inner_join_basic(db: Database) -> None:
    rows = db.select(User).join(Post, on=Post.author_id == User.id).all()
    # orphan post (author_id=None) excluded; 3 matched posts.
    assert len(rows) == 3
    for r in rows:
        assert isinstance(r, Row)
        assert isinstance(r.user, User)
        assert isinstance(r.post, Post)
        assert r.user.id == r.post.author_id


def test_inner_join_attribute_and_index_access(db: Database) -> None:
    rows = db.select(User).join(Post, on=Post.author_id == User.id).all()
    r = next(r for r in rows if r.post.id == 10)
    assert r[0].name == "Alice"
    assert r[1].title in {"A1", "A2"}
    assert r.user.id == 1
    assert r.post.author_id == 1
    assert len(r) == 2
    assert [r.user.name for r in rows]  # iterable


def test_inner_join_one_to_many_duplicates(db: Database) -> None:
    rows = db.select(User).join(Post, on=Post.author_id == User.id).all()
    alice_rows = [r for r in rows if r.user.name == "Alice"]
    assert len(alice_rows) == 2  # Alice has two posts; no dedup


# ---- LEFT join ----
def test_left_join_unmatched_right_is_none(db: Database) -> None:
    rows = db.select(User).join(Post, on=Post.author_id == User.id, kind="left").all()
    by_user: dict[str, list[Row]] = {}
    for r in rows:
        by_user.setdefault(r.user.name, []).append(r)
    # Alice: 2 posts, Bob: 1 post.
    assert len(by_user["Alice"]) == 2
    assert len(by_user["Bob"]) == 1
    # No user has zero posts in this dataset, but every slot is filled or None.
    for r in rows:
        assert r.user is not None


def test_left_join_with_user_having_no_posts(db: Database) -> None:
    db.insert(User(id=3, name="Carol"))
    rows = db.select(User).join(Post, on=Post.author_id == User.id, kind="left").all()
    carol = [r for r in rows if r.user.name == "Carol"]
    assert len(carol) == 1
    assert carol[0].post is None


# ---- join + where + order_by + limit ----
def test_join_where_order_limit(db: Database) -> None:
    rows = (
        db.select(User)
        .join(Post, on=Post.author_id == User.id)
        .where(User.name == "Alice")
        .order_by(Post.title)
        .limit(1)
        .all()
    )
    assert len(rows) == 1
    assert rows[0].user.name == "Alice"
    assert rows[0].post.title == "A1"


def test_join_where_on_right_model(db: Database) -> None:
    rows = db.select(User).join(Post, on=Post.author_id == User.id).where(Post.title == "B1").all()
    assert len(rows) == 1
    assert rows[0].user.name == "Bob"


def test_join_order_desc(db: Database) -> None:
    rows = (
        db.select(User).join(Post, on=Post.author_id == User.id).order_by(Post.id, desc=True).all()
    )
    ids = [r.post.id for r in rows]
    assert ids == sorted(ids, reverse=True)


# ---- 3-table chain ----
def test_three_table_chain_join(db: Database) -> None:
    rows = (
        db.select(User)
        .join(Post, on=Post.author_id == User.id)
        .join(Comment, on=Comment.post_id == Post.id)
        .all()
    )
    # Only post 10 has comments (2); both belong to Alice.
    assert len(rows) == 2
    for r in rows:
        assert r.user.name == "Alice"
        assert r.post.id == 10
        assert r.comment.post_id == 10


# ---- terminals ----
def test_join_first(db: Database) -> None:
    r = db.select(User).join(Post, on=Post.author_id == User.id).order_by(Post.id).first()
    assert r is not None
    assert r.post.id == 10


def test_join_first_empty(db: Database) -> None:
    db.insert(User(id=9, name="Nobody"))
    r = (
        db.select(User)
        .join(Post, on=Post.author_id == User.id)
        .where(User.name == "Nobody")
        .first()
    )
    assert r is None


def test_join_one(db: Database) -> None:
    r = db.select(User).join(Post, on=Post.author_id == User.id).where(Post.title == "B1").one()
    assert r.user.name == "Bob"


def test_join_one_raises_on_multiple(db: Database) -> None:
    with pytest.raises(MultipleObjectsReturned):
        (db.select(User).join(Post, on=Post.author_id == User.id).where(User.name == "Alice").one())


def test_join_count(db: Database) -> None:
    n = db.select(User).join(Post, on=Post.author_id == User.id).where(User.name == "Alice").count()
    assert n == 2


def test_join_exists(db: Database) -> None:
    q = db.select(User).join(Post, on=Post.author_id == User.id).where(User.name == "Bob")
    assert q.exists()
    q2 = q.where(User.name == "Carol")
    assert not q2.exists()


# ---- error handling ----
def test_join_condition_must_reference_joined_model(db: Database) -> None:
    with pytest.raises(QueryError):
        db.select(User).join(Post, on=Comment.post_id == Post.id).all()


def test_join_missing_intermediate_model(db: Database) -> None:
    with pytest.raises(QueryError):
        # Comment joined before Post exists in the query.
        db.select(User).join(Comment, on=Comment.post_id == Post.id).all()


def test_join_reversed_condition_works(db: Database) -> None:
    rows = db.select(User).join(Post, on=User.id == Post.author_id).where(User.name == "Bob").all()
    assert len(rows) == 1
    assert rows[0].post.title == "B1"
