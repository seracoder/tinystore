"""TinyStore field declarations.

``Field`` is a thin wrapper around :func:`pydantic.Field` that additionally
carries TinyStore-specific metadata (primary key, foreign key, unique, index,
on_delete). Because Pydantic v2's ``FieldInfo`` is ``@final``, the metadata is
attached through the supported ``json_schema_extra`` channel under a reserved
``__tinystore__`` key and read back during model construction.

TinyStore never lets the metadata leak into the generated JSON Schema: it is
popped before any schema is emitted (see :func:`strip_meta`).
"""

from __future__ import annotations

from typing import Any

from pydantic import Field as PydanticField
from pydantic.fields import FieldInfo as PydanticFieldInfo

__all__ = ["META_KEY", "Field", "OnDelete", "RelationshipField", "get_meta", "strip_meta"]

OnDelete = str  # one of "RESTRICT" | "CASCADE" | "SET_NULL"

META_KEY = "__tinystore__"


def _meta_dict(
    *,
    primary_key: bool,
    autoincrement: bool | None,
    unique: bool,
    index: bool,
    nullable: bool | None,
    foreign_key: str | None,
    on_delete: OnDelete,
    is_relationship: bool,
) -> dict[str, Any]:
    return {
        "primary_key": primary_key,
        "autoincrement": autoincrement,
        "unique": unique,
        "index": index,
        "nullable": nullable,
        "foreign_key": foreign_key,
        "on_delete": on_delete,
        "is_relationship": is_relationship,
    }


def get_meta(info: PydanticFieldInfo) -> dict[str, Any] | None:
    """Return TinyStore metadata attached to a Pydantic FieldInfo, if any."""
    extra = info.json_schema_extra
    if isinstance(extra, dict):
        meta = extra.get(META_KEY)
        if isinstance(meta, dict):
            return meta
    return None


def strip_meta(info: PydanticFieldInfo) -> None:
    """Remove the TinyStore metadata key so it never reaches the JSON Schema."""
    extra = info.json_schema_extra
    if isinstance(extra, dict) and META_KEY in extra:
        extra.pop(META_KEY, None)


def Field(  # intentionally shadows pydantic.Field
    default: Any = ...,
    *,
    primary_key: bool = False,
    autoincrement: bool | None = None,
    unique: bool = False,
    index: bool = False,
    nullable: bool | None = None,
    foreign_key: str | None = None,
    on_delete: OnDelete = "RESTRICT",
    **kwargs: Any,
) -> Any:
    """Declare a model field with TinyStore metadata.

    See the project plan for the full semantics of each keyword.
    """
    if autoincrement is None:
        autoincrement = primary_key

    pydantic_kwargs: dict[str, Any] = dict(kwargs)

    # Resolve the final default value (never keep it in kwargs to avoid dupes).
    pydantic_kwargs.pop("default", None)
    if default is ...:
        default = None if nullable is True else ...  # required field

    meta = _meta_dict(
        primary_key=primary_key,
        autoincrement=autoincrement,
        unique=unique,
        index=index,
        nullable=nullable,
        foreign_key=foreign_key,
        on_delete=on_delete,
        is_relationship=False,
    )

    extra = pydantic_kwargs.pop("json_schema_extra", None)
    merged: dict[str, Any] = dict(extra) if isinstance(extra, dict) else {}
    merged[META_KEY] = meta
    pydantic_kwargs["json_schema_extra"] = merged

    if default is ...:
        return PydanticField(**pydantic_kwargs)
    return PydanticField(default, **pydantic_kwargs)


def RelationshipField(  # factory named for clarity
    *, foreign_key: str, on_delete: OnDelete = "RESTRICT", **kwargs: Any
) -> Any:
    """Marker field info for an annotated relationship field."""
    kwargs.setdefault("default", None)
    meta = _meta_dict(
        primary_key=False,
        autoincrement=False,
        unique=False,
        index=False,
        nullable=None,
        foreign_key=foreign_key,
        on_delete=on_delete,
        is_relationship=True,
    )
    extra = kwargs.pop("json_schema_extra", None)
    merged: dict[str, Any] = dict(extra) if isinstance(extra, dict) else {}
    merged[META_KEY] = meta
    kwargs["json_schema_extra"] = merged
    return PydanticField(**kwargs)
