"""Pydantic <-> JSON row conversion with stable formatting.

TinyStore persists models as rows in JSON table files. Each row is a plain dict
produced by ``model_dump(mode='json')`` so that datetime/date/UUID/Enum and
nested JSON-compatible values are encoded as JSON scalars automatically by
Pydantic. Relationship fields are never persisted.
"""

from __future__ import annotations

import contextlib
import json
from typing import Any, TypeVar

from pydantic import BaseModel, TypeAdapter

__all__ = [
    "EMPTY_TABLE",
    "NEXT_ID_KEY",
    "ROWS_KEY",
    "VERSION_KEY",
    "decode_row",
    "dumps",
    "encode_row",
    "loads",
    "model_to_row",
    "row_to_model",
]

T = TypeVar("T", bound=BaseModel)

VERSION_KEY = "version"
NEXT_ID_KEY = "next_id"
ROWS_KEY = "rows"

CURRENT_TABLE_VERSION = 1
EMPTY_TABLE: dict[str, Any] = {
    VERSION_KEY: CURRENT_TABLE_VERSION,
    NEXT_ID_KEY: 1,
    ROWS_KEY: [],
}


def dumps(obj: Any) -> str:
    """Serialize with stable, human-readable formatting."""
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True)


def loads(text: str) -> Any:
    return json.loads(text)


def model_to_row(instance: BaseModel, *, exclude: frozenset[str] = frozenset()) -> dict[str, Any]:
    """Convert a model instance to a persistable row dict.

    ``exclude`` is the set of relationship field names to drop. The internal
    optimistic-concurrency version is attached under ``__version``.
    """
    row = instance.model_dump(mode="json", exclude=set(exclude))
    row["__version"] = getattr(instance, "_tinystore_version", 0)
    return row


def encode_row(instance: BaseModel, *, exclude: frozenset[str] = frozenset()) -> dict[str, Any]:
    return model_to_row(instance, exclude=exclude)


def row_to_model(
    model_cls: type[T], row: dict[str, Any], *, exclude: frozenset[str] = frozenset()
) -> T:
    """Convert a stored row dict back into a validated model instance.

    Internal fields (``__version``) are stripped before validation. Relationship
    fields are excluded (left as their default ``None``).
    """
    data = {k: v for k, v in row.items() if k != "__version"}
    instance = model_cls.model_validate(data)
    version = row.get("__version", 0)
    with contextlib.suppress(Exception):
        object.__setattr__(instance, "_tinystore_version", version)
    return instance


def decode_row(
    model_cls: type[T], row: dict[str, Any], *, exclude: frozenset[str] = frozenset()
) -> T:
    return row_to_model(model_cls, row, exclude=exclude)


# Reusable adapter for arbitrary JSON loads (kept for future schema validation).
_ANY_ADAPTER = TypeAdapter(Any)


def load_any(text: str) -> Any:
    return _ANY_ADAPTER.validate_json(text)
