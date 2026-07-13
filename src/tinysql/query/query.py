"""SelectQuery: typed, chainable query builder."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, TypeVar, cast

from ..exceptions import DoesNotExist, MultipleObjectsReturned
from ..serialization import row_to_model
from .expressions import Expression

if TYPE_CHECKING:
    from ..database import Database
    from ..model import Model

T = TypeVar("T", bound="Model")

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


class SelectQuery(Generic[T]):
    """A SELECT query over a single model.

    Reads rows from the table (under the database lock) and filters / orders /
    limits in memory. All terminal methods (``all``, ``first``, ``one``, ...)
    acquire the lock and materialize results.
    """

    def __init__(self, database: Database, model_cls: type[T]) -> None:
        self.db = database
        self.model_cls = model_cls
        self.schema = model_cls.__tinysql_schema__
        self.exclude = model_cls.__tinysql_relationship_fields__
        self._where: list[Expression] = []
        self._order: list[OrderClause] = []
        self._limit: int | None = None
        self._offset: int = 0

    # ---- builders (return self for chaining) ----
    def where(self, *exprs: Expression) -> SelectQuery[T]:
        for e in exprs:
            if not isinstance(e, Expression):
                raise TypeError(f"where() expects Expression, got {type(e).__name__}")
            self._where.append(e)
        return self

    def order_by(self, field_proxy: Any | str, *, desc: bool = False) -> SelectQuery[T]:
        name = getattr(field_proxy, "field", field_proxy)
        self._order.append(OrderClause(field=name, descending=desc))
        return self

    def limit(self, n: int) -> SelectQuery[T]:
        if n < 0:
            raise ValueError("limit must be non-negative")
        self._limit = n
        return self

    def offset(self, n: int) -> SelectQuery[T]:
        if n < 0:
            raise ValueError("offset must be non-negative")
        self._offset = n
        return self

    # ---- materialization ----
    def _rows(self) -> list[dict[str, Any]]:
        with self.db.lock():
            table = self.db.table(self.model_cls)
            rows = list(
                cast(
                    list[dict[str, Any]],
                    self.db._read_table_state(self.schema.name).get("rows", []),
                )
            )
            # Ensure index is built for the current rows.
            table.index.ensure(rows)

            if self._where:
                # Optimization: extract eq/in conditions on indexed fields and
                # narrow candidates via the index before applying full predicates.
                candidates = _index_narrow(table.index, rows, self._where)
                if candidates is not None:
                    rows = candidates
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

    def _decode(self, rows: list[dict[str, Any]]) -> list[T]:
        return [row_to_model(self.model_cls, r, exclude=self.exclude) for r in rows]

    def all(self) -> list[T]:
        return self._decode(self._rows())

    def first(self) -> T | None:
        prev_limit = self._limit
        self._limit = 1
        try:
            rows = self._rows()
        finally:
            self._limit = prev_limit
        if not rows:
            return None
        return self._decode(rows)[0]

    def one(self) -> T:
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

    def one_or_none(self) -> T | None:
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

    # ---- joins (Phase 4) ----
    def join(
        self,
        model: type[Model],
        *,
        on: Any,
        kind: str = "inner",
    ) -> Any:
        """Begin a multi-model join rooted at this query's model.

        Returns a :class:`~tinysql.query.joins.JoinQuery`; the ``on`` condition
        must compare two model field proxies, e.g.
        ``Post.author_id == User.id``.
        """
        from .joins import JoinQuery

        jq = JoinQuery(self.db, self.model_cls)
        jq.join(model, on=on, kind=kind)
        return jq


class _AndAll(Expression):
    """Internal: AND-combine a list of expressions."""

    __slots__ = ("exprs",)

    def __init__(self, exprs: list[Expression]) -> None:
        self.exprs = exprs

    def matches(self, row: dict[str, Any]) -> bool:
        return all(e.matches(row) for e in self.exprs)


def _index_narrow(
    index: Any,
    rows: list[dict[str, Any]],
    where: list[Expression],
) -> list[dict[str, Any]] | None:
    """Narrow candidate rows using eq/in conditions on indexed fields.

    Scans top-level where expressions for ``Comparison(eq)`` or ``In`` on
    indexed fields, intersects the matching row indices, and returns the
    narrowed candidate list.  Returns ``None`` when no index optimization
    applies (caller falls back to a full scan + predicate evaluation).
    """
    from .expressions import And, Comparison, In, Or

    candidate_sets: list[set[int]] = []

    def _extract(expr: Expression) -> None:
        if isinstance(expr, Comparison) and expr.op == "eq" and index.has_index(expr.field):
            indices = index.lookup(expr.field, expr.value)
            if indices is not None:
                candidate_sets.append(set(indices))
        elif isinstance(expr, In) and index.has_index(expr.field):
            indices = index.lookup_many(expr.field, expr.values)
            if indices is not None:
                candidate_sets.append(set(indices))
        elif isinstance(expr, And):
            for sub in expr.exprs:
                _extract(sub)

    for expr in where:
        if isinstance(expr, Or):
            continue  # can't safely narrow OR branches
        _extract(expr)

    if not candidate_sets:
        return None

    # Intersect all candidate sets (AND semantics).
    result_set = candidate_sets[0]
    for cs in candidate_sets[1:]:
        result_set &= cs

    if not result_set:
        # Empty intersection: fall back to full scan so that predicate
        # evaluation still runs (e.g. to raise strict type-mismatch errors).
        return None

    return [rows[i] for i in sorted(result_set)]
