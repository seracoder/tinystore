"""Relationship declarations.

Relationships are declared as annotated Pydantic-style fields using
:class:`Relationship` as the default marker::

    class Post(Model):
        author_id: int = Field(foreign_key="users.id")
        author: User | None = Relationship(foreign_key="author_id")

During model construction TinyStore detects these marker fields, records the
relationship metadata, and replaces the field's default with ``None`` so that
Pydantic sees a normal optional field. Relationship fields are *never*
persisted to disk; related objects are loaded explicitly via
``db.related(instance, name)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["Cardinality", "Relationship", "RelationshipMetadata"]


CARDINALITY_MANY = "many"
CARDINALITY_ONE = "one"


@dataclass(frozen=True)
class Relationship:
    """Declarative marker used as the default value of a relationship field.

    ``to`` may be omitted when the relationship target can be inferred from the
    field's type annotation (resolved after all models are registered).
    """

    foreign_key: str
    to: Any = None
    cardinality: str = CARDINALITY_MANY

    def __call__(self) -> None:  # pragma: no cover - defensive
        return None


@dataclass(frozen=True)
class RelationshipMetadata:
    """Resolved relationship metadata, stored on the model schema."""

    name: str
    foreign_key: str
    to_qualname: str
    cardinality: str = CARDINALITY_MANY


# Backwards-compatible alias.
Cardinality = str
