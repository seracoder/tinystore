"""Tests for in-memory indexes: PK lookup, unique check, query acceleration."""

from __future__ import annotations

from pathlib import Path

import pytest

from tinysql import Database, Field, Model


class Item(Model):
    id: int | None = Field(default=None, primary_key=True)
    sku: str = Field(unique=True)
    category: str = Field(index=True)
    name: str = Field(index=True)
    price: float


@pytest.fixture
def db(db_path: Path) -> Database:
    d = Database(db_path)
    d.register(Item)
    return d


def test_pk_index_always_built(db: Database) -> None:
    db.insert(Item(id=1, sku="A1", category="tools", name="Hammer", price=9.99))
    db.insert(Item(id=2, sku="A2", category="tools", name="Wrench", price=7.99))
    tbl = db.table(Item)
    assert tbl.index.has_index("id")


def test_unique_and_secondary_indexes_built(db: Database) -> None:
    tbl = db.table(Item)
    assert tbl.index.has_index("sku")  # unique
    assert tbl.index.has_index("category")  # index
    assert tbl.index.has_index("name")  # index
    assert not tbl.index.has_index("price")  # plain field


def test_index_lookup_finds_rows(db: Database) -> None:
    db.insert(Item(id=1, sku="A1", category="tools", name="Hammer", price=9.99))
    db.insert(Item(id=2, sku="A2", category="tools", name="Wrench", price=7.99))
    db.insert(Item(id=3, sku="A3", category="books", name="Guide", price=14.99))

    tbl = db.table(Item)
    rows = tbl._read_state()["rows"]
    tbl.index.build(rows)

    # PK lookup
    assert tbl.index.lookup("id", 2) == [1]
    assert tbl.index.lookup("id", 99) == []

    # Unique lookup
    assert tbl.index.lookup("sku", "A3") == [2]

    # Secondary index (category has two "tools")
    result = tbl.index.lookup("category", "tools")
    assert sorted(result) == [0, 1]


def test_get_uses_index_for_pk(db: Database) -> None:
    db.insert(Item(id=1, sku="A1", category="tools", name="Hammer", price=9.99))
    item = db.get(Item, 1)
    assert item.sku == "A1"


def test_get_by_uses_index(db: Database) -> None:
    db.insert(Item(id=1, sku="A1", category="tools", name="Hammer", price=9.99))
    db.insert(Item(id=2, sku="A2", category="tools", name="Wrench", price=7.99))
    item = db.get_by(Item, "sku", "A2")
    assert item.name == "Wrench"


def test_find_uses_index(db: Database) -> None:
    for i in range(10):
        cat = "tools" if i % 2 == 0 else "books"
        db.insert(Item(id=i, sku=f"S{i}", category=cat, name=f"Item{i}", price=float(i)))
    tools = db.table(Item).find("category", "tools")
    assert len(tools) == 5
    assert all(t.category == "tools" for t in tools)


def test_query_eq_uses_index(db: Database) -> None:
    for i in range(20):
        cat = "tools" if i % 2 == 0 else "books"
        db.insert(Item(id=i, sku=f"S{i}", category=cat, name=f"Item{i}", price=float(i)))
    # eq on indexed field 'category'
    books = db.select(Item).where(Item.category == "books").all()
    assert len(books) == 10
    assert all(b.category == "books" for b in books)


def test_query_in_uses_index(db: Database) -> None:
    for i in range(20):
        cat = "tools" if i % 2 == 0 else "books"
        db.insert(Item(id=i, sku=f"S{i}", category=cat, name=f"Item{i}", price=float(i)))
    result = db.select(Item).where(Item.id.in_([0, 5, 10])).all()
    assert {r.id for r in result} == {0, 5, 10}


def test_query_multiple_indexed_conditions(db: Database) -> None:
    """Multiple eq conditions on indexed fields should intersect."""
    for i in range(20):
        cat = "tools" if i % 2 == 0 else "books"
        db.insert(Item(id=i, sku=f"S{i}", category=cat, name="Same", price=float(i)))
    result = db.select(Item).where(
        Item.category == "tools", Item.name == "Same"
    ).all()
    assert len(result) == 10
    assert all(r.category == "tools" for r in result)


def test_query_non_indexed_field_scans(db: Database) -> None:
    db.insert(Item(id=1, sku="A1", category="tools", name="Hammer", price=9.99))
    db.insert(Item(id=2, sku="A2", category="tools", name="Wrench", price=7.99))
    # price is not indexed -> full scan
    result = db.select(Item).where(Item.price > 8.0).all()
    assert len(result) == 1
    assert result[0].name == "Hammer"


def test_index_rebuilt_after_transaction(db: Database) -> None:
    with db.transaction():
        db.insert(Item(id=1, sku="A1", category="tools", name="Hammer", price=9.99))
        db.insert(Item(id=2, sku="A2", category="tools", name="Wrench", price=7.99))
    # After commit, index should reflect committed data
    assert db.count(Item) == 2
    assert db.get(Item, 2).sku == "A2"
    assert db.get_by(Item, "sku", "A1").name == "Hammer"
