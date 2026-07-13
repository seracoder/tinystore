"""Shared test fixtures for TinyStore."""

from __future__ import annotations

import datetime
import uuid
from enum import Enum
from pathlib import Path
from typing import Any

import pytest

from tinystore import Database, Field, Model


class Status(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class Address(Model):
    """Nested model used to verify nested + JSON-compatible serialization."""

    street: str
    city: str


def _epoch() -> datetime.datetime:
    return datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC)


class User(Model):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    email: str = Field(unique=True, index=True)
    age: int | None = Field(default=None, index=True)
    country: str = "BD"
    status: Status = Status.ACTIVE
    created_at: datetime.datetime = Field(default_factory=_epoch)
    uid: uuid.UUID = Field(default_factory=uuid.uuid4)
    address: Address | None = Field(default=None)
    scores: list[int] = Field(default_factory=list)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_db"


@pytest.fixture
def db(db_path: Path) -> Database:
    return Database(db_path)


@pytest.fixture
def user_model() -> type[User]:
    return User


@pytest.fixture
def registered_db(db: Database, user_model: type[User]) -> Database:
    db.register(user_model)
    return db


@pytest.fixture
def make_user(user_model: type[User]) -> Any:
    def factory(**kwargs: Any) -> User:
        defaults: dict[str, Any] = {
            "name": "Alice",
            "email": "alice@example.com",
        }
        defaults.update(kwargs)
        return user_model(**defaults)

    return factory
