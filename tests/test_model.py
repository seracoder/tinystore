"""Tests for model registration and table naming."""

from __future__ import annotations

import pytest

from tinysql import Database, Field, Model
from tinysql.exceptions import SchemaError
from tinysql.model import _default_table_name, _pluralize, _to_snake_case


def test_snake_case() -> None:
    assert _to_snake_case("User") == "user"
    assert _to_snake_case("BlogPost") == "blog_post"
    assert _to_snake_case("HTTPSConnection") == "https_connection"
    assert _to_snake_case("SimpleXMLParser") == "simple_xml_parser"


def test_pluralize() -> None:
    assert _pluralize("user") == "users"
    assert _pluralize("box") == "boxes"
    assert _pluralize("category") == "categories"
    assert _pluralize("person") == "people"
    assert _pluralize("child") == "children"
    assert _pluralize("address") == "addresses"


def test_default_table_name() -> None:
    assert _default_table_name("User") == "users"
    assert _default_table_name("BlogPost") == "blog_posts"
    assert _default_table_name("Address") == "addresses"


def test_model_registers_table_name(registered_db: Database, user_model: type[Model]) -> None:
    schema = user_model.__tinysql_schema__
    assert schema.name == "users"
    assert schema.primary_key.name == "id"
    assert schema.primary_key.autoincrement is True


def test_meta_override_table_name(db: Database) -> None:
    class Account(Model):
        id: int | None = Field(default=None, primary_key=True)
        name: str

        class Meta:
            table_name = "accounts"

    db.register(Account)
    assert Account.__tinysql_schema__.name == "accounts"
    assert (db.root / "tables" / "accounts.json").exists()


def test_multiple_primary_keys_rejected() -> None:
    with pytest.raises(SchemaError):

        class Bad(Model):
            id: int | None = Field(default=None, primary_key=True)
            other: int = Field(default=0, primary_key=True)


def test_metadata_file_written(registered_db: Database) -> None:
    meta = registered_db.storage.read_metadata()
    assert meta is not None
    assert meta["version"] == 1
    assert "users" in meta["tables"]


def test_register_creates_table_file(registered_db: Database) -> None:
    assert (registered_db.root / "tables" / "users.json").exists()
    state = registered_db.storage.read_table("users")
    assert state["rows"] == []
    assert state["next_id"] == 1
