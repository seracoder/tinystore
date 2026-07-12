"""Query expression AST.

Expressions are composable objects (no ``eval``). Each expression implements
``matches(row)`` where ``row`` is a stored JSON-row dict. Field proxies are
produced by ``Model.field`` access (installed as non-data class descriptors in
:mod:`tinysql.model`); e.g. ``User.name == "Alice"`` yields a
:class:`Comparison`.

Evaluation semantics (see the project plan, decision D16):

* ``None`` / missing fields are "absent", not a type error. Ordering operators
  against ``None`` return ``False``; ``is_null``/``is_not_null`` are explicit.
* For ``==``/``!=``/``<``/``<=``/``>``/``>=``, if **both** the row value and the
  comparison value are non-``None`` and belong to incompatible runtime type
  groups, a :class:`~tinysql.exceptions.QueryError` is raised (strict mode).
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
    __slots__ = ("field", "op", "value")

    def __init__(self, field: str, op: str, value: Any) -> None:
        self.field = field
        self.op = op
        self.value = value

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
    __slots__ = ("field", "values")

    def __init__(self, field: str, values: Any) -> None:
        self.field = field
        self.values = list(values)

    def matches(self, row: dict[str, Any]) -> bool:
        actual = row.get(self.field)
        if actual is None:
            return False
        return any(actual == v for v in self.values)


class NotIn(Expression):
    __slots__ = ("field", "values")

    def __init__(self, field: str, values: Any) -> None:
        self.field = field
        self.values = list(values)

    def matches(self, row: dict[str, Any]) -> bool:
        actual = row.get(self.field)
        if actual is None:
            return True
        return all(actual != v for v in self.values)


class _StringOp(Expression):
    __slots__ = ("field", "value")

    def __init__(self, field: str, value: Any) -> None:
        self.field = field
        self.value = value

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
    __slots__ = ("field",)

    def __init__(self, field: str) -> None:
        self.field = field

    def matches(self, row: dict[str, Any]) -> bool:
        return row.get(self.field) is None


class IsNotNull(Expression):
    __slots__ = ("field",)

    def __init__(self, field: str) -> None:
        self.field = field

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

    def __eq__(self, value: Any) -> Comparison:  # type: ignore[override]
        return Comparison(self.field, "eq", value)

    def __ne__(self, value: Any) -> Comparison:  # type: ignore[override]
        return Comparison(self.field, "ne", value)

    def __lt__(self, value: Any) -> Comparison:
        return Comparison(self.field, "lt", value)

    def __le__(self, value: Any) -> Comparison:
        return Comparison(self.field, "le", value)

    def __gt__(self, value: Any) -> Comparison:
        return Comparison(self.field, "gt", value)

    def __ge__(self, value: Any) -> Comparison:
        return Comparison(self.field, "ge", value)

    __hash__ = None  # type: ignore[assignment]

    def in_(self, values: Any) -> In:
        return In(self.field, values)

    def not_in(self, values: Any) -> NotIn:
        return NotIn(self.field, values)

    def contains(self, value: Any) -> Contains:
        return Contains(self.field, value)

    def startswith(self, value: Any) -> StartsWith:
        return StartsWith(self.field, value)

    def endswith(self, value: Any) -> EndsWith:
        return EndsWith(self.field, value)

    def is_null(self) -> IsNull:
        return IsNull(self.field)

    def is_not_null(self) -> IsNotNull:
        return IsNotNull(self.field)

    def __repr__(self) -> str:
        return f"{self.model.__name__}.{self.field}"
