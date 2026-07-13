"""Stress test: 10k-row insert + query performance and correctness."""

from __future__ import annotations

from pathlib import Path

import pytest

from tinysql import Database, Field, Model


class Record(Model):
    id: int | None = Field(default=None, primary_key=True)
    category: str = Field(index=True)
    value: int = Field(index=True)
    name: str = Field(unique=True)


@pytest.fixture
def big_db(db_path: Path) -> Database:
    d = Database(db_path)
    d.register(Record)
    return d


def test_bulk_insert_10k_rows(big_db: Database) -> None:
    """insert_many of 10k rows should complete and set correct next_id."""
    records = [
        Record(id=i, category=f"cat_{i % 100}", value=i, name=f"name_{i}")
        for i in range(10_000)
    ]
    big_db.insert_many(records)
    assert big_db.count(Record) == 10_000
    assert big_db.get(Record, 9999).name == "name_9999"


def test_indexed_query_on_10k_rows(big_db: Database) -> None:
    """eq on an indexed field should find the right row quickly."""
    records = [
        Record(id=i, category=f"cat_{i % 100}", value=i, name=f"name_{i}")
        for i in range(10_000)
    ]
    big_db.insert_many(records)

    result = big_db.select(Record).where(Record.category == "cat_42").all()
    assert len(result) == 100
    assert all(r.category == "cat_42" for r in result)


def test_unique_lookup_on_10k_rows(big_db: Database) -> None:
    records = [
        Record(id=i, category=f"cat_{i % 100}", value=i, name=f"name_{i}")
        for i in range(10_000)
    ]
    big_db.insert_many(records)

    r = big_db.get_by(Record, "name", "name_5000")
    assert r.value == 5000


def test_pagination_on_10k_rows(big_db: Database) -> None:
    records = [
        Record(id=i, category=f"cat_{i % 100}", value=i, name=f"name_{i}")
        for i in range(10_000)
    ]
    big_db.insert_many(records)

    page1 = big_db.select(Record).order_by(Record.id).limit(20).offset(0).all()
    page2 = big_db.select(Record).order_by(Record.id).limit(20).offset(20).all()
    assert len(page1) == 20
    assert len(page2) == 20
    assert page1[-1].id < page2[0].id


def test_mixed_indexed_and_non_indexed_query(big_db: Database) -> None:
    """Multiple conditions: indexed + non-indexed should still work."""
    records = [
        Record(id=i, category=f"cat_{i % 100}", value=i, name=f"name_{i}")
        for i in range(10_000)
    ]
    big_db.insert_many(records)

    result = (
        big_db.select(Record)
        .where(Record.category == "cat_5", Record.value > 9000)
        .all()
    )
    assert all(r.category == "cat_5" and r.value > 9000 for r in result)


def test_check_passes_on_large_db(big_db: Database) -> None:
    records = [
        Record(id=i, category=f"cat_{i % 100}", value=i, name=f"name_{i}")
        for i in range(10_000)
    ]
    big_db.insert_many(records)
    assert big_db.check() == []
