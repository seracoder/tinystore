"""Query expression AST.

Expressions are composable objects (no ``eval``). Each expression implements
``matches(row)`` where ``row`` is a stored JSON-row dict. Field proxies are
produced by ``Model.field`` access (installed as non-data class descriptors in
:mod:`tinystore.model`); e.g. ``User.name == "Alice"`` yields a
:class:`Comparison`.

Evaluation semantics (see the project plan, decision D16):

* ``None`` / missing fields are "absent", not a type error. Ordering operators
  against ``None`` return ``False``; ``is_null``/``is_not_null`` are explicit.
* For ``==``/``!=``/``<``/``<=``/``>``/``>=``, if **both** the row value and the
  comparison value are non-``None`` and belong to incompatible runtime type
  groups, a :class:`~tinystore.exceptions.QueryError` is raised (strict mode).
"""

from __future__ import annotations

import operator
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from ..exceptions import QueryError

__all__ = [
    "And",
    "Comparison",
    "Contains",
    "EndsWith",
    "Expression",
    "FieldProxy",
    "In",
    "IsNotNull",
    "IsNull",
    "JoinCondition",
    "Not",
    "NotIn",
    "Or",
    "StartsWith",
]


_TYPE_GROUPS = {
    bool: "number",
    int: "number",
    float: "number",
    str: "str",
    bytes: "bytes",
    list: "sequence",
    tuple: "sequence",
    dict: "mapping",
    set: "set",
}


def _type_group(v: Any) -> str:
    return _TYPE_GROUPS.get(type(v), "other")


def _compatible(a: Any, b: Any) -> bool:
    """Whether two non-None values are order-comparable."""
    return _type_group(a) == _type_group(b)


def _require_compatible(field: str, a: Any, b: Any, op: str) -> None:
    if a is None or b is None:
        return
    if not _compatible(a, b):
        raise QueryError(
            f"Cannot compare {field!r} {op} {b!r}: incompatible types "
            f"({_type_group(a)} vs {_type_group(b)})"
        )


class Expression(ABC):
    """Base class for all query expressions."""

    @abstractmethod
    def matches(self, row: dict[str, Any]) -> bool: ...

    def __and__(self, other: Expression) -> And:
        return And(self, other)

    def __or__(self, other: Expression) -> Or:
        return Or(self, other)

    def __invert__(self) -> Not:
        return Not(self)

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


_COMPARATORS: dict[str, tuple[Callable[[Any, Any], bool], str]] = {
    "eq": (operator.eq, "=="),
    "ne": (operator.ne, "!="),
    "lt": (operator.lt, "<"),
    "le": (operator.le, "<="),
    "gt": (operator.gt, ">"),
    "ge": (operator.ge, ">="),
}


class Comparison(Expression):
    __slots__ = ("field", "model", "op", "value")

    def __init__(self, field: str, op: str, value: Any) -> None:
        self.field = field
        self.op = op
        self.value = value
        self.model: Any = None

    def matches(self, row: dict[str, Any]) -> bool:
        actual = row.get(self.field)
        cmp_func, symbol = _COMPARATORS[self.op]
        if self.value is None:
            # Comparing against None: equality semantics on absence.
            if self.op == "eq":
                return actual is None
            if self.op == "ne":
                return actual is not None
            # ordering against None -> no match
            return False
        if actual is None:
            return self.op == "ne"  # missing != value; missing == value is False
        _require_compatible(self.field, actual, self.value, symbol)
        try:
            return bool(cmp_func(actual, self.value))
        except TypeError as exc:
            raise QueryError(
                f"Cannot compare {self.field!r} {symbol} {self.value!r}: {exc}"
            ) from exc

    def __repr__(self) -> str:
        _, symbol = _COMPARATORS[self.op]
        return f"{self.field}{symbol}{self.value!r}"


class In(Expression):
    __slots__ = ("field", "model", "values")

    def __init__(self, field: str, values: Any) -> None:
        self.field = field
        self.values = list(values)
        self.model: Any = None

    def matches(self, row: dict[str, Any]) -> bool:
        actual = row.get(self.field)
        if actual is None:
            return False
        return any(actual == v for v in self.values)


class NotIn(Expression):
    __slots__ = ("field", "model", "values")

    def __init__(self, field: str, values: Any) -> None:
        self.field = field
        self.values = list(values)
        self.model: Any = None

    def matches(self, row: dict[str, Any]) -> bool:
        actual = row.get(self.field)
        if actual is None:
            return True
        return all(actual != v for v in self.values)


class _StringOp(Expression):
    __slots__ = ("field", "model", "value")

    def __init__(self, field: str, value: Any) -> None:
        self.field = field
        self.value = value
        self.model: Any = None

    def _as_str(self, field: str, v: Any) -> str:
        if isinstance(v, str):
            return v
        raise QueryError(
            f"{type(self).__name__} on {field!r} requires a string value, got {type(v).__name__}"
        )

    @abstractmethod
    def matches(self, row: dict[str, Any]) -> bool: ...


class Contains(_StringOp):
    def matches(self, row: dict[str, Any]) -> bool:
        actual = row.get(self.field)
        if actual is None:
            return False
        return self._as_str(self.field, self.value) in self._as_str(self.field, actual)


class StartsWith(_StringOp):
    def matches(self, row: dict[str, Any]) -> bool:
        actual = row.get(self.field)
        if actual is None:
            return False
        return self._as_str(self.field, actual).startswith(self._as_str(self.field, self.value))


class EndsWith(_StringOp):
    def matches(self, row: dict[str, Any]) -> bool:
        actual = row.get(self.field)
        if actual is None:
            return False
        return self._as_str(self.field, actual).endswith(self._as_str(self.field, self.value))


class IsNull(Expression):
    __slots__ = ("field", "model")

    def __init__(self, field: str) -> None:
        self.field = field
        self.model: Any = None

    def matches(self, row: dict[str, Any]) -> bool:
        return row.get(self.field) is None


class IsNotNull(Expression):
    __slots__ = ("field", "model")

    def __init__(self, field: str) -> None:
        self.field = field
        self.model: Any = None

    def matches(self, row: dict[str, Any]) -> bool:
        return row.get(self.field) is not None


class And(Expression):
    __slots__ = ("exprs",)

    def __init__(self, *exprs: Expression) -> None:
        self.exprs = exprs

    def matches(self, row: dict[str, Any]) -> bool:
        return all(e.matches(row) for e in self.exprs)


class Or(Expression):
    __slots__ = ("exprs",)

    def __init__(self, *exprs: Expression) -> None:
        self.exprs = exprs

    def matches(self, row: dict[str, Any]) -> bool:
        return any(e.matches(row) for e in self.exprs)


class Not(Expression):
    __slots__ = ("expr",)

    def __init__(self, expr: Expression) -> None:
        self.expr = expr

    def matches(self, row: dict[str, Any]) -> bool:
        return not self.expr.matches(row)


class JoinCondition:
    """A cross-table equality predicate produced by comparing two field proxies.

    ``Post.author_id == User.id`` yields ``JoinCondition(Post, "author_id",
    User, "id")``. The two sides are stored neutrally; the join resolves which
    side is the newly-joined model and which is already in the result set.
    """

    __slots__ = ("a_field", "a_model", "b_field", "b_model")

    def __init__(
        self, a_model: Any, a_field: str, b_model: Any, b_field: str
    ) -> None:
        self.a_model = a_model
        self.a_field = a_field
        self.b_model = b_model
        self.b_field = b_field

    def __repr__(self) -> str:
        return (
            f"{self.a_model.__name__}.{self.a_field} == "
            f"{self.b_model.__name__}.{self.b_field}"
        )


class FieldProxy:
    """Returned by ``Model.field`` class access; builds expressions.

    ``User.name == "Alice"`` returns a :class:`Comparison`. Note: defining
    ``__eq__`` makes instances unhashable, which is fine (proxies are transient
    builders, not stored in sets/dicts).
    """

    __slots__ = ("field", "field_type", "model")

    def __init__(self, model: type, field: str, field_type: str = "any") -> None:
        self.model = model
        self.field = field
        self.field_type = field_type

    def __eq__(self, value: Any) -> Comparison | JoinCondition:  # type: ignore[override]
        if isinstance(value, FieldProxy):
            return JoinCondition(self.model, self.field, value.model, value.field)
        cmp = Comparison(self.field, "eq", value)
        cmp.model = self.model
        return cmp

    def __ne__(self, value: Any) -> Comparison:  # type: ignore[override]
        cmp = Comparison(self.field, "ne", value)
        cmp.model = self.model
        return cmp

    def __lt__(self, value: Any) -> Comparison:
        cmp = Comparison(self.field, "lt", value)
        cmp.model = self.model
        return cmp

    def __le__(self, value: Any) -> Comparison:
        cmp = Comparison(self.field, "le", value)
        cmp.model = self.model
        return cmp

    def __gt__(self, value: Any) -> Comparison:
        cmp = Comparison(self.field, "gt", value)
        cmp.model = self.model
        return cmp

    def __ge__(self, value: Any) -> Comparison:
        cmp = Comparison(self.field, "ge", value)
        cmp.model = self.model
        return cmp

    __hash__ = None  # type: ignore[assignment]

    def in_(self, values: Any) -> In:
        expr = In(self.field, values)
        expr.model = self.model
        return expr

    def not_in(self, values: Any) -> NotIn:
        expr = NotIn(self.field, values)
        expr.model = self.model
        return expr

    def contains(self, value: Any) -> Contains:
        expr = Contains(self.field, value)
        expr.model = self.model
        return expr

    def startswith(self, value: Any) -> StartsWith:
        expr = StartsWith(self.field, value)
        expr.model = self.model
        return expr

    def endswith(self, value: Any) -> EndsWith:
        expr = EndsWith(self.field, value)
        expr.model = self.model
        return expr

    def is_null(self) -> IsNull:
        expr = IsNull(self.field)
        expr.model = self.model
        return expr

    def is_not_null(self) -> IsNotNull:
        expr = IsNotNull(self.field)
        expr.model = self.model
        return expr

    def __repr__(self) -> str:
        return f"{self.model.__name__}.{self.field}"
