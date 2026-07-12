"""SelectQuery: typed, chainable query builder."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from ..exceptions import DoesNotExist, MultipleObjectsReturned
from ..serialization import row_to_model
from .expressions import Expression

if TYPE_CHECKING:
    from ..database import Database
    from ..model import Model

__all__ = ["OrderClause", "SelectQuery"]

_TYPE_RANK = {None: 0, bool: 1, int: 2, float: 2, str: 3, bytes: 4}


def _type_rank(v: Any) -> int:
    if v is None:
        return 0
    return _TYPE_RANK.get(type(v), 5)


def _sort_key(
    field_name: str, descending: bool
) -> tuple[Callable[[dict[str, Any]], tuple[int, Any]], bool]:
    def key(row: dict[str, Any]) -> tuple[int, Any]:
        v = row.get(field_name)
        rank = _type_rank(v)
        # Within a type group, use the value; None handled by rank.
        return (rank, v if v is not None else 0)

    return key, descending


@dataclass
class OrderClause:
    field: str
    descending: bool = False


class SelectQuery:
    """A SELECT query over a single model.

    Reads rows from the table (under the database lock) and filters / orders /
    limits in memory. All terminal methods (``all``, ``first``, ``one``, ...)
    acquire the lock and materialize results.
    """

    def __init__(self, database: Database, model_cls: type[Model]) -> None:
        self.db = database
        self.model_cls = model_cls
        self.schema = model_cls.__tinysql_schema__
        self.exclude = model_cls.__tinysql_relationship_fields__
        self._where: list[Expression] = []
        self._order: list[OrderClause] = []
        self._limit: int | None = None
        self._offset: int = 0

    # ---- builders (return self for chaining) ----
    def where(self, *exprs: Expression) -> SelectQuery:
        for e in exprs:
            if not isinstance(e, Expression):
                raise TypeError(f"where() expects Expression, got {type(e).__name__}")
            self._where.append(e)
        return self

    def order_by(self, field_proxy: Any | str, *, desc: bool = False) -> SelectQuery:
        name = getattr(field_proxy, "field", field_proxy)
        self._order.append(OrderClause(field=name, descending=desc))
        return self

    def limit(self, n: int) -> SelectQuery:
        if n < 0:
            raise ValueError("limit must be non-negative")
        self._limit = n
        return self

    def offset(self, n: int) -> SelectQuery:
        if n < 0:
            raise ValueError("offset must be non-negative")
        self._offset = n
        return self

    # ---- materialization ----
    def _rows(self) -> list[dict[str, Any]]:
        with self.db.lock():
            rows = list(
                cast(
                    list[dict[str, Any]],
                    self.db._read_table_state(self.schema.name).get("rows", []),
                )
            )
            if self._where:
                combined = _AndAll(self._where)
                rows = [r for r in rows if combined.matches(r)]
            # ordering (stable; apply in reverse for stable multi-key)
            for clause in reversed(self._order):
                key, desc = _sort_key(clause.field, clause.descending)
                rows = sorted(rows, key=key, reverse=desc)
            if self._offset:
                rows = rows[self._offset :]
            if self._limit is not None:
                rows = rows[: self._limit]
            return rows

    def _decode(self, rows: list[dict[str, Any]]) -> list[Model]:
        return [row_to_model(self.model_cls, r, exclude=self.exclude) for r in rows]

    def all(self) -> list[Model]:
        return self._decode(self._rows())

    def first(self) -> Model | None:
        prev_limit = self._limit
        self._limit = 1
        try:
            rows = self._rows()
        finally:
            self._limit = prev_limit
        if not rows:
            return None
        return self._decode(rows)[0]

    def one(self) -> Model:
        prev_limit = self._limit
        self._limit = None
        try:
            rows = self._rows()
        finally:
            self._limit = prev_limit
        if not rows:
            raise DoesNotExist(f"{self.model_cls.__name__} query returned no rows")
        if len(rows) > 1:
            raise MultipleObjectsReturned(
                f"{self.model_cls.__name__} query returned {len(rows)} rows; expected one"
            )
        return self._decode(rows)[0]

    def one_or_none(self) -> Model | None:
        prev_limit = self._limit
        self._limit = None
        try:
            rows = self._rows()
        finally:
            self._limit = prev_limit
        if not rows:
            return None
        if len(rows) > 1:
            raise MultipleObjectsReturned(
                f"{self.model_cls.__name__} query returned {len(rows)} rows; expected one"
            )
        return self._decode(rows)[0]

    def count(self) -> int:
        prev_limit = self._limit
        prev_offset = self._offset
        self._limit = None
        self._offset = 0
        try:
            return len(self._rows())
        finally:
            self._limit = prev_limit
            self._offset = prev_offset

    def exists(self) -> bool:
        prev_limit = self._limit
        self._limit = 1
        try:
            return bool(self._rows())
        finally:
            self._limit = prev_limit


class _AndAll(Expression):
    """Internal: AND-combine a list of expressions."""

    __slots__ = ("exprs",)

    def __init__(self, exprs: list[Expression]) -> None:
        self.exprs = exprs

    def matches(self, row: dict[str, Any]) -> bool:
        return all(e.matches(row) for e in self.exprs)
