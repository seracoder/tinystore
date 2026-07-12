"""Schema metadata: per-table descriptions, fingerprints, and compatibility checks.

A :class:`TableSchema` is a serializable snapshot of a model's structure. It is
persisted in ``metadata.json`` so that reopening a database can detect
incompatible schema changes rather than silently corrupting data.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "METADATA_VERSION",
    "FieldMetadata",
    "SchemaChange",
    "TableSchema",
    "classify_change",
]

METADATA_VERSION = 1


@dataclass(frozen=True)
class FieldMetadata:
    """Static description of a single model field as seen by TinySQL."""

    name: str
    type_str: str
    primary_key: bool = False
    autoincrement: bool = False
    unique: bool = False
    index: bool = False
    nullable: bool = True
    foreign_key: str | None = None
    on_delete: str = "RESTRICT"
    default_repr: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FieldMetadata:
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass(frozen=True)
class TableSchema:
    """Serializable schema snapshot for one table."""

    name: str
    model_qualname: str
    fields: tuple[FieldMetadata, ...] = field(default_factory=tuple)
    relationships: tuple[tuple[str, str, str, str], ...] = field(default_factory=tuple)

    @property
    def primary_key(self) -> FieldMetadata:
        for f in self.fields:
            if f.primary_key:
                return f
        raise SchemaError(f"Table {self.name!r} has no primary key field")

    def field(self, name: str) -> FieldMetadata | None:
        for f in self.fields:
            if f.name == name:
                return f
        return None

    @property
    def unique_fields(self) -> tuple[FieldMetadata, ...]:
        return tuple(f for f in self.fields if f.unique)

    @property
    def indexed_fields(self) -> tuple[FieldMetadata, ...]:
        return tuple(f for f in self.fields if (f.index or f.unique or f.primary_key))

    @property
    def foreign_keys(self) -> tuple[FieldMetadata, ...]:
        return tuple(f for f in self.fields if f.foreign_key)

    def fingerprint(self) -> str:
        canonical = json.dumps(
            {
                "name": self.name,
                "fields": [f.to_dict() for f in self.fields],
                "relationships": list(self.relationships),
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "model_qualname": self.model_qualname,
            "fields": [f.to_dict() for f in self.fields],
            "relationships": [list(r) for r in self.relationships],
            "fingerprint": self.fingerprint(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TableSchema:
        return cls(
            name=data["name"],
            model_qualname=data.get("model_qualname", data["name"]),
            fields=tuple(FieldMetadata.from_dict(f) for f in data.get("fields", [])),
            relationships=tuple(tuple(r) for r in data.get("relationships", [])),
        )


# Late import to avoid a cycle for the error type only.
from .exceptions import SchemaError  # noqa: E402  (cyclic avoidance)


@dataclass(frozen=True)
class SchemaChange:
    """A single difference between two table schemas.

    ``kind`` is one of: ``additive`` (safe), ``breaking`` (rejected),
    ``compatible`` (no semantic impact, e.g. model qualname rename).
    """

    kind: str
    detail: str


def classify_change(stored: TableSchema, current: TableSchema) -> list[SchemaChange]:
    """Compare a previously-persisted schema to the currently-registered one.

    Returns a list of changes. If any change is ``breaking``, the caller should
    raise :class:`~tinysql.exceptions.SchemaError`.
    """
    changes: list[SchemaChange] = []

    if stored.name != current.name:
        changes.append(SchemaChange("breaking", f"table renamed: {stored.name} -> {current.name}"))

    stored_fields = {f.name: f for f in stored.fields}
    current_fields = {f.name: f for f in current.fields}

    for name, f in current_fields.items():
        if name not in stored_fields:
            if f.nullable or f.default_repr is not None:
                changes.append(SchemaChange("additive", f"new field {name!r} (nullable/defaulted)"))
            else:
                changes.append(
                    SchemaChange("breaking", f"new non-nullable field {name!r} has no default")
                )
            continue
        old = stored_fields[name]
        diffs = _field_diffs(old, f)
        for d in diffs:
            changes.append(d)

    for name in stored_fields:
        if name not in current_fields:
            changes.append(SchemaChange("breaking", f"field {name!r} was removed"))

    return changes


def _field_diffs(old: FieldMetadata, new: FieldMetadata) -> list[SchemaChange]:
    out: list[SchemaChange] = []
    breaking_attrs = ("type_str", "primary_key", "autoincrement", "foreign_key", "on_delete")
    for attr in breaking_attrs:
        ov = getattr(old, attr)
        nv = getattr(new, attr)
        if ov != nv:
            out.append(
                SchemaChange(
                    "breaking",
                    f"field {old.name!r} attribute {attr!r} changed: {ov!r} -> {nv!r}",
                )
            )
    # nullable: True->False is breaking; False->True is additive
    if not old.nullable and new.nullable:
        out.append(SchemaChange("additive", f"field {old.name!r} became nullable"))
    elif old.nullable and not new.nullable:
        out.append(SchemaChange("breaking", f"field {old.name!r} became non-nullable"))
    # unique / index transitions are constraints, not shape; treat as breaking to be safe.
    if old.unique != new.unique:
        out.append(
            SchemaChange(
                "breaking",
                f"field {old.name!r} unique changed: {old.unique} -> {new.unique}",
            )
        )
    if old.index != new.index:
        out.append(SchemaChange("compatible", f"field {old.name!r} index flag changed"))
    return out
