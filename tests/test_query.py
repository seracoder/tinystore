"""Tests for the query expression AST and SelectQuery."""

from __future__ import annotations

import pytest

from tinysql import Database
from tinysql.exceptions import DoesNotExist, MultipleObjectsReturned, QueryError


@pytest.fixture
def populated_db(registered_db: Database, make_user) -> Database:
    registered_db.insert(make_user(name="Alice", email="a@x.com", age=30, country="US"))
    registered_db.insert(make_user(name="Bob", email="b@x.com", age=17, country="BD"))
    registered_db.insert(make_user(name="Charlie", email="c@x.com", age=25, country="BD"))
    registered_db.insert(make_user(name="Alicia", email="d@x.com", age=40, country="BD"))
    return registered_db


def test_eq(populated_db: Database, user_model) -> None:
    r = populated_db.select(user_model).where(user_model.name == "Alice").all()
    assert [u.name for u in r] == ["Alice"]


def test_ne(populated_db: Database, user_model) -> None:
    r = populated_db.select(user_model).where(user_model.name != "Alice").all()
    assert sorted(u.name for u in r) == ["Alicia", "Bob", "Charlie"]


def test_lt_le_gt_ge(populated_db: Database, user_model) -> None:
    gt = populated_db.select(user_model).where(user_model.age > 25).all()
    assert sorted(u.name for u in gt) == ["Alice", "Alicia"]
    ge = populated_db.select(user_model).where(user_model.age >= 25).all()
    assert len(ge) == 3
    lt = populated_db.select(user_model).where(user_model.age < 25).all()
    assert [u.name for u in lt] == ["Bob"]
    le = populated_db.select(user_model).where(user_model.age <= 17).all()
    assert [u.name for u in le] == ["Bob"]


def test_in_not_in(populated_db: Database, user_model) -> None:
    r = populated_db.select(user_model).where(user_model.country.in_(["US", "BD"])).count()
    assert r == 4
    r = populated_db.select(user_model).where(user_model.country.not_in(["US"])).count()
    assert r == 3


def test_contains(populated_db: Database, user_model) -> None:
    r = populated_db.select(user_model).where(user_model.name.contains("lic")).all()
    assert sorted(u.name for u in r) == ["Alice", "Alicia"]


def test_startswith_endswith(populated_db: Database, user_model) -> None:
    r = populated_db.select(user_model).where(user_model.name.startswith("Ali")).all()
    assert sorted(u.name for u in r) == ["Alice", "Alicia"]
    r = populated_db.select(user_model).where(user_model.email.endswith(".com")).count()
    assert r == 4


def test_is_null_is_not_null(registered_db: Database, user_model, make_user) -> None:
    registered_db.insert(make_user(name="HasAge", email="a@x.com", age=30))
    registered_db.insert(make_user(name="NoAge", email="b@x.com", age=None))
    nulls = registered_db.select(user_model).where(user_model.age.is_null()).all()
    assert [u.name for u in nulls] == ["NoAge"]
    not_nulls = registered_db.select(user_model).where(user_model.age.is_not_null()).all()
    assert [u.name for u in not_nulls] == ["HasAge"]


def test_and(populated_db: Database, user_model) -> None:
    r = (
        populated_db.select(user_model)
        .where((user_model.age >= 18) & (user_model.country == "BD"))
        .order_by(user_model.name)
        .all()
    )
    assert [u.name for u in r] == ["Alicia", "Charlie"]


def test_or(populated_db: Database, user_model) -> None:
    # Chained .where() is AND, so this should be empty.
    r = (
        populated_db.select(user_model)
        .where(user_model.name == "Alice")
        .where(user_model.name == "Bob")
        .all()
    )
    assert r == []
    # Explicit OR with parentheses.
    r = (
        populated_db.select(user_model)
        .where((user_model.name == "Alice") | (user_model.name == "Bob"))
        .all()
    )
    assert sorted(u.name for u in r) == ["Alice", "Bob"]


def test_or_explicit(populated_db: Database, user_model) -> None:
    r = (
        populated_db.select(user_model)
        .where((user_model.name == "Alice") | (user_model.name == "Bob"))
        .all()
    )
    assert sorted(u.name for u in r) == ["Alice", "Bob"]


def test_not(populated_db: Database, user_model) -> None:
    r = populated_db.select(user_model).where(~(user_model.country == "BD")).all()
    assert [u.name for u in r] == ["Alice"]


def test_complex_precedence(populated_db: Database, user_model) -> None:
    r = (
        populated_db.select(user_model)
        .where((user_model.age >= 18) & ((user_model.country == "BD") | (user_model.country == "US")))
        .order_by(user_model.name)
        .limit(20)
        .all()
    )
    assert sorted(u.name for u in r) == ["Alice", "Alicia", "Charlie"]


def test_order_by_asc_desc(populated_db: Database, user_model) -> None:
    asc = populated_db.select(user_model).order_by(user_model.age).all()
    assert [u.age for u in asc if u.age is not None] == [17, 25, 30, 40]
    desc = populated_db.select(user_model).order_by(user_model.age, desc=True).all()
    assert [u.age for u in desc if u.age is not None] == [40, 30, 25, 17]


def test_limit_offset(populated_db: Database, user_model) -> None:
    page = populated_db.select(user_model).order_by(user_model.name).limit(2).offset(1).all()
    assert [u.name for u in page] == ["Alicia", "Bob"]
    # offset beyond range
    empty = populated_db.select(user_model).offset(100).all()
    assert empty == []


def test_first(populated_db: Database, user_model) -> None:
    first = populated_db.select(user_model).order_by(user_model.age, desc=True).first()
    assert first is not None
    assert first.age == 40


def test_first_none(registered_db: Database, user_model) -> None:
    assert registered_db.select(user_model).where(user_model.name == "ghost").first() is None


def test_one(populated_db: Database, user_model) -> None:
    u = populated_db.select(user_model).where(user_model.email == "a@x.com").one()
    assert u.name == "Alice"


def test_one_does_not_exist(populated_db: Database, user_model) -> None:
    with pytest.raises(DoesNotExist):
        populated_db.select(user_model).where(user_model.name == "ghost").one()


def test_one_multiple(populated_db: Database, user_model) -> None:
    with pytest.raises(MultipleObjectsReturned):
        populated_db.select(user_model).where(user_model.country == "BD").one()


def test_one_or_none(populated_db: Database, user_model) -> None:
    assert populated_db.select(user_model).where(user_model.name == "ghost").one_or_none() is None
    u = populated_db.select(user_model).where(user_model.email == "a@x.com").one_or_none()
    assert u is not None and u.name == "Alice"


def test_count(populated_db: Database, user_model) -> None:
    assert populated_db.select(user_model).where(user_model.country == "BD").count() == 3


def test_exists(populated_db: Database, user_model) -> None:
    assert populated_db.select(user_model).where(user_model.name == "Alice").exists()
    assert not populated_db.select(user_model).where(user_model.name == "ghost").exists()


def test_strict_type_mismatch_raises(populated_db: Database, user_model) -> None:
    with pytest.raises(QueryError):
        populated_db.select(user_model).where(user_model.age > "adult").all()
    with pytest.raises(QueryError):
        populated_db.select(user_model).where(user_model.age == "thirty").all()


def test_ordering_against_none_returns_false(registered_db: Database, user_model, make_user) -> None:
    registered_db.insert(make_user(name="NoAge", email="a@x.com", age=None))
    r = registered_db.select(user_model).where(user_model.age > 10).all()
    assert r == []


def test_none_sorts_first(populated_db: Database, user_model, make_user) -> None:
    populated_db.insert(make_user(name="NoAge", email="z@x.com", age=None))
    r = populated_db.select(user_model).order_by(user_model.age).all()
    assert r[0].name == "NoAge"  # None first


def test_where_requires_expression(registered_db: Database, user_model) -> None:
    with pytest.raises(TypeError):
        registered_db.select(user_model).where("not an expression")  # type: ignore[arg-type]


def test_query_returns_typed_instances(populated_db: Database, user_model) -> None:
    r = populated_db.select(user_model).all()
    assert all(isinstance(x, user_model) for x in r)
