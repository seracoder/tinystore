"""JoinQuery: in-memory INNER / LEFT joins across registered models.

Joins are evaluated in memory: every participating table is read fully and
combined with nested loops. This is deliberate and documented — TinyStore stores
rows as JSON files, so a disk-efficient join is not the goal of v1. The result
of a join is a list of :class:`Row` objects, one per combined row, with
attribute access by lowercased model name (``row.user``, ``row.post``) and
positional access (``row[0]``).

Example
-------

.. code-block:: python

    rows = (
        db.select(User)
        .join(Post, on=Post.author_id == User.id)
        .where(User.name == "Alice")
        .order_by(Post.title)
        .all()
    )
    for r in rows:
        print(r.user.name, r.post.title)
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from ..exceptions import DoesNotExist, MultipleObjectsReturned, QueryError
from ..serialization import row_to_model
from .expressions import And, Expression, JoinCondition, Not, Or

if TYPE_CHECKING:
    from ..database import Database
    from ..model import Model

__all__ = ["JoinQuery", "Row"]


class Row:
    """A single joined result row.

    Behaves like a tuple of model instances (in the order the models were
    added to the query) and also supports attribute access by lowercased model
    name. Unmatched RIGHT rows in a LEFT join contribute ``None`` to their
    slot.
    """

    __slots__ = ("_models", "_values")

    def __init__(self, models: tuple[type[Model], ...], values: tuple[Any, ...]) -> None:
        self._models = models
        self._values = values

    def __getitem__(self, index: int) -> Any:
        return self._values[index]

    def __iter__(self) -> Iterator[Any]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        for model, value in zip(self._models, self._values, strict=True):
            if model.__name__.lower() == name:
                return value
        raise AttributeError(
            f"Row has no column named {name!r}; available: "
            f"{[m.__name__.lower() for m in self._models]}"
        )

    def __repr__(self) -> str:
        parts = ", ".join(
            f"{m.__name__.lower()}={v!r}" for m, v in zip(self._models, self._values, strict=True)
        )
        return f"Row({parts})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Row):
            return self._values == other._values
        if isinstance(other, tuple):
            return self._values == other
        return NotImplemented

    __hash__ = None  # type: ignore[assignment]


class JoinQuery:
    """A SELECT across multiple models with in-memory joins."""

    def __init__(self, database: Database, base_model: type[Model]) -> None:
        self.db = database
        self._models: list[type[Model]] = [base_model]
        self._joins: list[tuple[type[Model], JoinCondition, str]] = []
        self._where: list[Expression] = []
        self._order: list[tuple[type[Model], str, bool]] = []
        self._limit: int | None = None
        self._offset: int = 0

    # ---- builders ----
    def join(
        self,
        model: type[Model],
        *,
        on: JoinCondition,
        kind: str = "inner",
    ) -> JoinQuery:
        kind = kind.lower()
        if kind not in ("inner", "left"):
            raise QueryError(f"Unsupported join kind {kind!r}; use 'inner' or 'left'")
        if not isinstance(on, JoinCondition):
            raise QueryError(
                "join(on=...) must be a cross-model condition like Post.author_id == User.id"
            )
        if on.a_model is not model and on.b_model is not model:
            raise QueryError(
                f"join condition {on!r} does not reference the joined model {model.__name__!r}"
            )
        other = on.b_model if on.a_model is model else on.a_model
        if other not in self._models:
            raise QueryError(
                f"join condition {on!r} references {other.__name__!r}, which is "
                "not yet in the query; join it first"
            )
        self._models.append(model)
        self._joins.append((model, on, kind))
        return self

    def where(self, *exprs: Expression) -> JoinQuery:
        for e in exprs:
            if not isinstance(e, Expression):
                raise TypeError(f"where() expects Expression, got {type(e).__name__}")
            self._where.append(e)
        return self

    def order_by(self, field_proxy: Any, *, desc: bool = False) -> JoinQuery:
        model = getattr(field_proxy, "model", None)
        name = getattr(field_proxy, "field", field_proxy)
        if not isinstance(name, str):
            raise QueryError("order_by() expects a field proxy or field name")
        if model is None:
            model = self._models[0]
        if model not in self._models:
            raise QueryError(f"order_by references {model.__name__!r} which is not in the query")
        self._order.append((model, name, desc))
        return self

    def limit(self, n: int) -> JoinQuery:
        if n < 0:
            raise ValueError("limit must be non-negative")
        self._limit = n
        return self

    def offset(self, n: int) -> JoinQuery:
        if n < 0:
            raise ValueError("offset must be non-negative")
        self._offset = n
        return self

    # ---- materialization ----
    def _load_rows(self, model: type[Model]) -> list[dict[str, Any]]:
        name = model.__tinystore_schema__.name
        return list(self.db._read_table_state(name).get("rows", []))

    def _decode(self, model: type[Model], row: dict[str, Any] | None) -> Any:
        if row is None:
            return None
        return row_to_model(model, row, exclude=model.__tinystore_relationship_fields__)

    def _combine(self) -> list[dict[type[Model], dict[str, Any] | None]]:
        combined: list[dict[type[Model], dict[str, Any] | None]] = [
            {self._models[0]: r} for r in self._load_rows(self._models[0])
        ]
        for model, cond, kind in self._joins:
            right_rows = self._load_rows(model)
            new_combined: list[dict[type[Model], dict[str, Any] | None]] = []
            for left in combined:
                matched = False
                for right in right_rows:
                    if _cond_satisfied(cond, model, right, left):
                        merged = dict(left)
                        merged[model] = right
                        new_combined.append(merged)
                        matched = True
                if not matched and kind == "left":
                    merged = dict(left)
                    merged[model] = None
                    new_combined.append(merged)
            combined = new_combined
        return combined

    def _apply_where(
        self, combined: list[dict[type[Model], dict[str, Any] | None]]
    ) -> list[dict[type[Model], dict[str, Any] | None]]:
        if not self._where:
            return combined
        out = []
        for row_map in combined:
            if all(_expr_matches(e, row_map) for e in self._where):
                out.append(row_map)
        return out

    def _apply_order(
        self, combined: list[dict[type[Model], dict[str, Any] | None]]
    ) -> list[dict[type[Model], dict[str, Any] | None]]:
        rows = list(combined)
        for model, field, desc in reversed(self._order):

            def key_fn(
                rm: dict[type[Model], dict[str, Any] | None],
                m: type[Model] = model,
                f: str = field,
            ) -> tuple[int, Any]:
                return _sort_key_val((rm.get(m) or {}).get(f))

            rows.sort(key=key_fn, reverse=desc)
        return rows

    def _materialize(self) -> list[Row]:
        models_tuple = tuple(self._models)
        with self.db.lock():
            combined = self._combine()
            combined = self._apply_where(combined)
            combined = self._apply_order(combined)
            if self._offset:
                combined = combined[self._offset :]
            if self._limit is not None:
                combined = combined[: self._limit]
            return [
                Row(models_tuple, tuple(self._decode(m, rm.get(m)) for m in self._models))
                for rm in combined
            ]

    # ---- terminals ----
    def all(self) -> list[Row]:
        return self._materialize()

    def first(self) -> Row | None:
        prev = self._limit
        self._limit = 1
        try:
            rows = self._materialize()
        finally:
            self._limit = prev
        return rows[0] if rows else None

    def one(self) -> Row:
        prev = self._limit
        self._limit = None
        try:
            rows = self._materialize()
        finally:
            self._limit = prev
        if not rows:
            raise DoesNotExist("join query returned no rows")
        if len(rows) > 1:
            raise MultipleObjectsReturned(f"join query returned {len(rows)} rows; expected one")
        return rows[0]

    def one_or_none(self) -> Row | None:
        prev = self._limit
        self._limit = None
        try:
            rows = self._materialize()
        finally:
            self._limit = prev
        if not rows:
            return None
        if len(rows) > 1:
            raise MultipleObjectsReturned(f"join query returned {len(rows)} rows; expected one")
        return rows[0]

    def count(self) -> int:
        prev_limit = self._limit
        prev_offset = self._offset
        self._limit = None
        self._offset = 0
        try:
            return len(self._materialize())
        finally:
            self._limit = prev_limit
            self._offset = prev_offset

    def exists(self) -> bool:
        prev = self._limit
        self._limit = 1
        try:
            return bool(self._materialize())
        finally:
            self._limit = prev


def _cond_satisfied(
    cond: JoinCondition,
    new_model: type[Model],
    new_row: dict[str, Any],
    existing: dict[type[Model], dict[str, Any] | None],
) -> bool:
    if cond.a_model is new_model:
        new_field, other_model, other_field = cond.a_field, cond.b_model, cond.b_field
    else:
        new_field, other_model, other_field = cond.b_field, cond.a_model, cond.a_field
    other_row = existing.get(other_model)
    if other_row is None:
        return False
    return new_row.get(new_field) == other_row.get(other_field)


def _expr_matches(expr: Any, row_map: dict[type[Model], dict[str, Any] | None]) -> bool:
    if isinstance(expr, And):
        return all(_expr_matches(e, row_map) for e in expr.exprs)
    if isinstance(expr, Or):
        return any(_expr_matches(e, row_map) for e in expr.exprs)
    if isinstance(expr, Not):
        return not _expr_matches(expr.expr, row_map)
    model = getattr(expr, "model", None)
    if model is None:
        raise QueryError(
            "join where() expressions must reference a model field, e.g. User.name == 'Alice'"
        )
    row = row_map.get(model)
    if row is None:
        return False
    return bool(expr.matches(row))


def _sort_key_val(v: Any) -> tuple[int, Any]:
    rank = {None: 0, bool: 1, int: 2, float: 2, str: 3, bytes: 4}.get(type(v), 5)
    return (rank, v if v is not None else 0)
