"""Tests for schema metadata and mismatch detection."""

from __future__ import annotations

import pytest

from tinysql import Database, Field, Model
from tinysql.exceptions import SchemaError


def test_additive_new_nullable_field_ok(db_path) -> None:
    class V1(Model):
        id: int | None = Field(default=None, primary_key=True)
        name: str

        class Meta:
            table_name = "things"

    db = Database(db_path)
    db.register(V1)
    db.insert(V1(name="x"))
    del db

    class V2(Model):
        id: int | None = Field(default=None, primary_key=True)
        name: str
        nickname: str | None = Field(default=None)  # additive

        class Meta:
            table_name = "things"

    db2 = Database(db_path)
    db2.register(V2)  # should not raise
    assert db2.all(V2)[0].name == "x"


def test_additive_new_defaulted_field_ok(db_path) -> None:
    class V1(Model):
        id: int | None = Field(default=None, primary_key=True)

        class Meta:
            table_name = "things"

    db = Database(db_path)
    db.register(V1)
    db.insert(V1())
    del db

    class V2(Model):
        id: int | None = Field(default=None, primary_key=True)
        count: int = Field(default=0)

        class Meta:
            table_name = "things"

    db2 = Database(db_path)
    db2.register(V2)
    assert db2.all(V2)[0].count == 0


def test_breaking_removed_field_raises(db_path) -> None:
    class V1(Model):
        id: int | None = Field(default=None, primary_key=True)
        name: str

        class Meta:
            table_name = "things"

    db = Database(db_path)
    db.register(V1)
    del db

    class V2(Model):
        id: int | None = Field(default=None, primary_key=True)

        class Meta:
            table_name = "things"

    db2 = Database(db_path)
    with pytest.raises(SchemaError):
        db2.register(V2)


def test_breaking_type_change_raises(db_path) -> None:
    class V1(Model):
        id: int | None = Field(default=None, primary_key=True)
        age: int

        class Meta:
            table_name = "things"

    db = Database(db_path)
    db.register(V1)
    del db

    class V2(Model):
        id: int | None = Field(default=None, primary_key=True)
        age: str

        class Meta:
            table_name = "things"

    db2 = Database(db_path)
    with pytest.raises(SchemaError):
        db2.register(V2)


def test_breaking_non_nullable_added_raises(db_path) -> None:
    class V1(Model):
        id: int | None = Field(default=None, primary_key=True)

        class Meta:
            table_name = "things"

    db = Database(db_path)
    db.register(V1)
    db.insert(V1())
    del db

    class V2(Model):
        id: int | None = Field(default=None, primary_key=True)
        required_field: str  # non-nullable, no default -> breaking

        class Meta:
            table_name = "things"

    db2 = Database(db_path)
    with pytest.raises(SchemaError):
        db2.register(V2)


def test_reset_schema_clears_metadata(registered_db: Database) -> None:
    registered_db.reset_schema()
    meta = registered_db.storage.read_metadata()
    assert meta is not None
    assert meta["tables"] == {}


def test_fingerprint_stable(registered_db: Database) -> None:
    schema = registered_db._schemas["users"]
    fp1 = schema.fingerprint()
    fp2 = schema.fingerprint()
    assert fp1 == fp2
    assert len(fp1) == 64  # sha256 hex
