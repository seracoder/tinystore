"""TinySQL model base.

``Model`` is a thin layer over :class:`pydantic.BaseModel`. It uses a custom
metaclass (subclassing Pydantic's own ``ModelMetaclass``) so that class-level
field access — e.g. ``Post.title`` — resolves to a :class:`FieldProxy` for both
static type checkers and runtime query building. Field metadata (primary key,
unique, index, foreign key, relationships) is introspected via Pydantic's own
``__pydantic_init_subclass__`` hook and recorded on a ``TableSchema`` attached
to the class as ``__tinysql_schema__``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, ConfigDict, PrivateAttr
from pydantic_core import PydanticUndefined

from .fields import get_meta, strip_meta
from .query.expressions import FieldProxy
from .relationships import CARDINALITY_MANY, Relationship, RelationshipMetadata
from .schema import FieldMetadata, TableSchema

if TYPE_CHECKING:
    from pydantic._internal._model_construction import ModelMetaclass as _BaseMeta
else:
    _BaseMeta = type(BaseModel)

__all__ = ["Model"]

_CAMEL_RE_1 = re.compile(r"(.)([A-Z][a-z]+)")
_CAMEL_RE_2 = re.compile(r"([a-z0-9])([A-Z])")

_IRREGULAR_PLURALS: dict[str, str] = {
    "person": "people",
    "child": "children",
    "mouse": "mice",
    "goose": "geese",
    "foot": "feet",
    "tooth": "teeth",
    "ox": "oxen",
    "man": "men",
    "woman": "women",
}


def _to_snake_case(name: str) -> str:
    s = _CAMEL_RE_1.sub(r"\1_\2", name)
    s = _CAMEL_RE_2.sub(r"\1_\2", s)
    return s.lower()


def _pluralize(word: str) -> str:
    lower = word.lower()
    if lower in _IRREGULAR_PLURALS:
        return _IRREGULAR_PLURALS[lower]
    if lower.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    if lower.endswith("y") and len(word) >= 2 and lower[-2] not in "aeiou":
        return word[:-1] + "ies"
    if lower.endswith(("fe",)):
        return word[:-2] + "ves"
    if lower.endswith("f") and not lower.endswith("ff"):
        return word[:-1] + "ves"
    return word + "s"


def _default_table_name(model_name: str) -> str:
    return _pluralize(_to_snake_case(model_name))


def _type_to_str(annotation: Any) -> str:
    if annotation is None or annotation is type(None):
        return "None"
    if isinstance(annotation, str):
        return annotation
    module = getattr(annotation, "__module__", "")
    qualname = (
        getattr(annotation, "__qualname__", None)
        or getattr(annotation, "_name", None)
        or repr(annotation)
    )
    if qualname == repr(annotation):
        return qualname
    if module and module not in ("builtins", "typing"):
        return f"{module}.{qualname}"
    return qualname


class _TinySQLMeta(_BaseMeta):
    """TinySQL model metaclass.

    ``__getattr__`` resolves class-level model-field access (e.g.
    ``Post.title``) to :class:`FieldProxy` so that static type checkers
    and IDEs can resolve the attribute. At runtime, non-data descriptors
    installed in ``__pydantic_init_subclass__`` handle the actual access;
    this method is never reached for known fields (the descriptor in
    ``cls.__dict__`` takes priority). It is a fallback that exists purely
    to give type checkers a return type to infer from.
    """

    def __getattr__(cls, name: str) -> FieldProxy:
        for klass in cls.__mro__:
            schema = klass.__dict__.get("__tinysql_schema__")
            if schema is not None:
                for fm in schema.fields:
                    if fm.name == name:
                        return FieldProxy(cls, name, fm.type_str)
                break
        raise AttributeError(f"type {cls.__name__!r} has no attribute {name!r}")


class Model(BaseModel, metaclass=_TinySQLMeta):
    """Base class for all TinySQL models.

    Subclass it, declare Pydantic fields, and optionally a nested ``Meta``
    class to override the table name::

        class User(Model):
            id: int | None = Field(default=None, primary_key=True)
            name: str

            class Meta:
                table_name = "accounts"
    """

    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
        validate_assignment=True,
        use_enum_values=False,
    )

    # Internal optimistic-concurrency version. Not exposed to users; managed by
    # the engine. Populated on load, checked+incremented on write.
    _tinysql_version: int = PrivateAttr(default=0)

    __tinysql_schema__: ClassVar[TableSchema]
    __tinysql_relationship_fields__: ClassVar[frozenset[str]] = frozenset()

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)

        meta = getattr(cls, "Meta", None)
        table_name = getattr(meta, "table_name", None) if meta else None
        if not table_name:
            table_name = _default_table_name(cls.__name__)

        field_metas: list[FieldMetadata] = []
        relationship_fields: set[str] = set()
        relationship_metadatas: list[RelationshipMetadata] = []

        for name, info in list(cls.model_fields.items()):
            default_val = info.default
            if isinstance(default_val, Relationship):
                relationship_fields.add(name)
                relationship_metadatas.append(
                    RelationshipMetadata(
                        name=name,
                        foreign_key=default_val.foreign_key,
                        to_qualname=_type_to_str(info.annotation),
                        cardinality=default_val.cardinality or CARDINALITY_MANY,
                    )
                )
                # Replace the marker with a real None default so the field
                # behaves as a normal optional Pydantic attribute.
                info.default = None
                if info.default_factory is not None:
                    info.default_factory = None
                field_metas.append(
                    FieldMetadata(
                        name=name,
                        type_str=_type_to_str(info.annotation),
                        nullable=True,
                        default_repr="None",
                    )
                )
                continue

            is_tinysql_meta = get_meta(info)
            if is_tinysql_meta is not None:
                primary_key = bool(is_tinysql_meta.get("primary_key", False))
                unique = bool(is_tinysql_meta.get("unique", False))
                index = bool(is_tinysql_meta.get("index", False))
                autoincrement = bool(is_tinysql_meta.get("autoincrement", False))
                foreign_key = is_tinysql_meta.get("foreign_key")
                on_delete = is_tinysql_meta.get("on_delete", "RESTRICT")
                # Strip the metadata so it doesn't leak into the JSON schema.
                strip_meta(info)
            else:
                primary_key = unique = index = autoincrement = False
                foreign_key = None
                on_delete = "RESTRICT"

            has_default = info.default is not PydanticUndefined or info.default_factory is not None
            nullable = has_default

            default_repr: str | None
            if info.default is not PydanticUndefined:
                default_repr = repr(info.default)
            elif info.default_factory is not None:
                default_repr = "<factory>"
            else:
                default_repr = None

            field_metas.append(
                FieldMetadata(
                    name=name,
                    type_str=_type_to_str(info.annotation),
                    primary_key=primary_key,
                    autoincrement=autoincrement,
                    unique=unique,
                    index=index,
                    nullable=nullable,
                    foreign_key=foreign_key,
                    on_delete=on_delete,
                    default_repr=default_repr,
                )
            )

        # Validate single primary key.
        pks = [f for f in field_metas if f.primary_key]
        if len(pks) > 1:
            from .exceptions import SchemaError

            raise SchemaError(
                f"Model {cls.__name__!r} declares more than one primary key: "
                f"{[p.name for p in pks]}"
            )

        schema = TableSchema(
            name=table_name,
            model_qualname=f"{cls.__module__}.{cls.__qualname__}",
            fields=tuple(field_metas),
            relationships=tuple(
                (r.name, r.foreign_key, r.to_qualname, r.cardinality)
                for r in relationship_metadatas
            ),
        )
        cls.__tinysql_schema__ = schema
        cls.__tinysql_relationship_fields__ = frozenset(relationship_fields)

        # Install field-access descriptors so ``Model.field`` returns a
        # FieldProxy for query building (class access) while leaving instance
        # access (which reads from __dict__) untouched. These are NON-data
        # descriptors (no __set__), so they never interfere with Pydantic's
        # validate_assignment or instance attribute storage.
        for fm in field_metas:
            if fm.name in relationship_fields:
                continue
            setattr(cls, fm.name, _FieldAccessorDescriptor(fm.name, fm.type_str))

        # Rebuild so the replaced defaults take effect.
        cls.model_rebuild(force=True)


class _FieldAccessorDescriptor:
    """Non-data descriptor: returns a :class:`FieldProxy` on class access."""

    __slots__ = ("name", "type_str")

    def __init__(self, name: str, type_str: str) -> None:
        self.name = name
        self.type_str = type_str

    def __get__(self, instance: Any, owner: type | None = None) -> Any:
        if instance is None:
            # Class access -> query field proxy.
            assert owner is not None
            return FieldProxy(owner, self.name, self.type_str)
        # Instance access -> defer to the instance's own __dict__ (set by Pydantic).
        return instance.__dict__.get(self.name)
