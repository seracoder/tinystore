"""Table-level CRUD operations over a storage backend.

``Table[T]`` is bound to a model class and a :class:`~tinystore.database.Database`.
All operations acquire the database-wide write lock (reentrant, so an active
transaction is fine) and validate constraints (unique, optimistic concurrency)
before writing. Single-op writes are atomic per table file; multi-table
all-or-nothing durability arrives with the transaction journal in Phase 5.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Generic, TypeVar

from .exceptions import DoesNotExist, ForeignKeyError, StaleDataError, UniqueConstraintError
from .indexes import IndexManager
from .serialization import EMPTY_TABLE, model_to_row, row_to_model

if TYPE_CHECKING:
    from .database import Database
    from .model import Model
    from .schema import FieldMetadata, TableSchema

T = TypeVar("T", bound="Model")

__all__ = ["Table"]


def _parse_fk(spec: str) -> tuple[str, str]:
    """Split a ``"table.column"`` foreign-key reference into its parts."""
    if "." not in spec:
        return "", ""
    table, _, column = spec.partition(".")
    return table, column


def _fk_accepts_null(schema: TableSchema, field_name: str) -> bool:
    for f in schema.fields:
        if f.name == field_name:
            return f.nullable
    return False


class Table(Generic[T]):
    """CRUD interface for a single model."""

    def __init__(self, database: Database, model_cls: type[T]) -> None:
        self.db = database
        self.model_cls = model_cls
        self.schema = model_cls.__tinystore_schema__
        self.exclude = model_cls.__tinystore_relationship_fields__
        self.index = IndexManager(self.schema)

    # ---- internal helpers ----
    def _read_state(self) -> dict[str, Any]:
        state = self.db._read_table_state(self.schema.name)
        self.index.ensure(state.get("rows", []))
        return state

    def _write_state(self, data: dict[str, Any]) -> None:
        self.db._write_table_state(self.schema.name, data)

    def _pk_field(self) -> str:
        return self.schema.primary_key.name

    def _decode(self, row: dict[str, Any]) -> T:
        return row_to_model(self.model_cls, row, exclude=self.exclude)

    def _encode(self, instance: T) -> dict[str, Any]:
        return model_to_row(instance, exclude=self.exclude)

    def _find_index(self, rows: list[dict[str, Any]], pk: object) -> int:
        """Find the row index for *pk*, using the PK index when available."""
        pk_field = self._pk_field()
        indexed = self.index.lookup(pk_field, pk)
        if indexed is not None:
            return indexed[0] if indexed else -1
        for i, row in enumerate(rows):
            if row.get(pk_field) == pk:
                return i
        return -1

    def _check_unique(
        self,
        rows: list[dict[str, Any]],
        instance: T,
        exclude_pk: object | None = None,
    ) -> None:
        pk_field = self._pk_field()
        for field in self.schema.unique_fields:
            value = getattr(instance, field.name)
            if value is None and field.nullable:
                continue
            # Fast path: use the index if this field is indexed (unique fields
            # always are).
            indexed = self.index.lookup(field.name, value)
            if indexed is not None:
                for i in indexed:
                    if exclude_pk is not None and rows[i].get(pk_field) == exclude_pk:
                        continue
                    raise UniqueConstraintError(self.schema.name, field.name, value)
            else:
                for row in rows:
                    if exclude_pk is not None and row.get(pk_field) == exclude_pk:
                        continue
                    if row.get(field.name) == value:
                        raise UniqueConstraintError(self.schema.name, field.name, value)

    def _check_foreign_keys(self, instance: T) -> None:
        """Validate that every non-null FK on ``instance`` points to an existing row."""
        for field in self.schema.foreign_keys:
            value = getattr(instance, field.name)
            if value is None and field.nullable:
                continue
            ref_table, ref_column = _parse_fk(field.foreign_key or "")
            if not ref_table:
                continue
            if not self.db._table_exists(ref_table):
                raise ForeignKeyError(
                    f"Foreign key {self.schema.name}.{field.name}={value!r} references "
                    f"unknown table {ref_table!r}"
                )
            ref_state = self.db._read_table_state(ref_table)
            ref_rows = ref_state.get("rows", [])
            if not any(r.get(ref_column) == value for r in ref_rows):
                raise ForeignKeyError(
                    f"Foreign key {self.schema.name}.{field.name}={value!r} does not "
                    f"reference an existing {ref_table}.{ref_column}"
                )

    def _handle_cascade_on_delete(self, pk_value: object) -> None:
        """Propagate this row's deletion to dependents per each FK's on_delete policy."""
        visited: set[tuple[str, object]] = set()
        self._cascade_delete(self.schema.name, pk_value, visited)

    def _cascade_delete(
        self,
        table_name: str,
        pk_value: object,
        visited: set[tuple[str, object]],
    ) -> None:
        """Recursively apply on_delete for every row referencing ``pk_value``.

        Each level runs in two phases so that RESTRICT semantics match SQL: any
        RESTRICT FK with a live dependent aborts the whole delete before any
        CASCADE/SET_NULL mutation occurs. ``visited`` is shared across the
        recursion so cyclic references (including self-referential FKs) terminate.
        """
        key = (table_name, pk_value)
        if key in visited:
            return
        visited.add(key)

        refs: list[tuple[TableSchema, FieldMetadata]] = []
        for dep_schema in self.db._schemas.values():
            for fk in dep_schema.foreign_keys:
                ref_table, _ = _parse_fk(fk.foreign_key or "")
                if ref_table == table_name:
                    refs.append((dep_schema, fk))

        for dep_schema, fk in refs:
            if (fk.on_delete or "RESTRICT").upper() != "RESTRICT":
                continue
            rows = self.db._read_table_state(dep_schema.name)["rows"]
            if any(r.get(fk.name) == pk_value for r in rows):
                raise ForeignKeyError(
                    f"Cannot delete {table_name} {pk_value!r}: row(s) in "
                    f"{dep_schema.name}.{fk.name} reference it (on_delete=RESTRICT)"
                )

        for dep_schema, fk in refs:
            on_delete = (fk.on_delete or "RESTRICT").upper()
            if on_delete == "RESTRICT":
                continue
            dep_state = self.db._read_table_state(dep_schema.name)
            rows = dep_state["rows"]
            dependents = [r for r in rows if r.get(fk.name) == pk_value]
            if not dependents:
                continue
            if on_delete == "SET_NULL":
                if not _fk_accepts_null(dep_schema, fk.name):
                    raise ForeignKeyError(
                        f"Cannot SET_NULL on {dep_schema.name}.{fk.name}: "
                        "field is not nullable"
                    )
                for row in rows:
                    if row.get(fk.name) == pk_value:
                        row[fk.name] = None
                self.db._write_table_state(dep_schema.name, dep_state)
            elif on_delete == "CASCADE":
                dep_state["rows"] = [r for r in rows if r.get(fk.name) != pk_value]
                self.db._write_table_state(dep_schema.name, dep_state)
                dep_pk = dep_schema.primary_key.name
                for row in dependents:
                    child_pk = row.get(dep_pk)
                    if child_pk is not None:
                        self._cascade_delete(dep_schema.name, child_pk, visited)
            else:
                raise ForeignKeyError(
                    f"Unknown on_delete policy {on_delete!r} on "
                    f"{dep_schema.name}.{fk.name}"
                )

    # ---- public CRUD ----
    def insert(self, instance: T) -> T:
        with self.db._ensure_transaction():
            state = self._read_state()
            rows: list[dict[str, Any]] = state["rows"]
            pk_field = self._pk_field()
            pk_meta = self.schema.primary_key

            pk_value = getattr(instance, pk_field)
            if pk_value is None:
                if pk_meta.autoincrement:
                    pk_value = state.get("next_id", 1)
                    setattr(instance, pk_field, pk_value)
                    state["next_id"] = pk_value + 1
                else:
                    raise ValueError(
                        f"Cannot insert {self.model_cls.__name__} without a primary key value"
                    )
            elif pk_meta.autoincrement and isinstance(pk_value, int):
                # Explicit id: keep the counter ahead to avoid future collisions.
                state["next_id"] = max(state.get("next_id", 1), pk_value + 1)

            if self._find_index(rows, pk_value) >= 0:
                from .exceptions import UniqueConstraintError as _UCE

                raise _UCE(self.schema.name, pk_field, pk_value)

            self._check_unique(rows, instance)
            self._check_foreign_keys(instance)

            # New rows start at version 1.
            object.__setattr__(instance, "_tinystore_version", 1)
            rows.append(self._encode(instance))
            self._write_state(state)
            return instance

    def insert_many(self, instances: list[T]) -> list[T]:
        if not instances:
            return []
        with self.db._ensure_transaction():
            state = self._read_state()
            rows: list[dict[str, Any]] = state["rows"]
            pk_field = self._pk_field()
            pk_meta = self.schema.primary_key
            result: list[T] = []
            for instance in instances:
                pk_value = getattr(instance, pk_field)
                if pk_value is None:
                    if pk_meta.autoincrement:
                        pk_value = state.get("next_id", 1)
                        setattr(instance, pk_field, pk_value)
                        state["next_id"] = pk_value + 1
                    else:
                        raise ValueError(
                            f"Cannot insert {self.model_cls.__name__} without a primary key value"
                        )
                elif pk_meta.autoincrement and isinstance(pk_value, int):
                    state["next_id"] = max(state.get("next_id", 1), pk_value + 1)
                if self._find_index(rows, pk_value) >= 0:
                    raise UniqueConstraintError(self.schema.name, pk_field, pk_value)
                self._check_unique(rows, instance)
                self._check_foreign_keys(instance)
                object.__setattr__(instance, "_tinystore_version", 1)
                rows.append(self._encode(instance))
                result.append(instance)
            self._write_state(state)
            return result

    def get(self, pk: object) -> T:
        with self.db.lock():
            rows = self._read_state()["rows"]
            idx = self._find_index(rows, pk)
            if idx < 0:
                raise DoesNotExist(
                    f"{self.model_cls.__name__} with {self._pk_field()}={pk!r} does not exist"
                )
            return self._decode(rows[idx])

    def get_by(self, field: str, value: object) -> T:
        with self.db.lock():
            rows = self._read_state()["rows"]
            indexed = self.index.lookup(field, value)
            if indexed is not None:
                matches = [rows[i] for i in indexed]
            else:
                matches = [r for r in rows if r.get(field) == value]
            if not matches:
                raise DoesNotExist(
                    f"{self.model_cls.__name__} where {field}={value!r} does not exist"
                )
            if len(matches) > 1:
                from .exceptions import MultipleObjectsReturned

                raise MultipleObjectsReturned(
                    f"{self.model_cls.__name__} where {field}={value!r} returned "
                    f"{len(matches)} rows"
                )
            return self._decode(matches[0])

    def all(self) -> list[T]:
        with self.db.lock():
            rows = self._read_state()["rows"]
            return [self._decode(r) for r in rows]

    def find(self, field: str, value: object) -> list[T]:
        with self.db.lock():
            rows = self._read_state()["rows"]
            indexed = self.index.lookup(field, value)
            if indexed is not None:
                return [self._decode(rows[i]) for i in indexed]
            return [self._decode(r) for r in rows if r.get(field) == value]

    def update(self, instance: T) -> T:
        with self.db._ensure_transaction():
            state = self._read_state()
            rows: list[dict[str, Any]] = state["rows"]
            pk_field = self._pk_field()
            pk_value = getattr(instance, pk_field)
            idx = self._find_index(rows, pk_value)
            if idx < 0:
                raise DoesNotExist(
                    f"Cannot update {self.model_cls.__name__} with {pk_field}={pk_value!r}: "
                    "not found"
                )
            stored = rows[idx]
            stored_version = stored.get("__version", 0)
            loaded_version = getattr(instance, "_tinystore_version", 0)
            if self.db.optimistic_concurrency and stored_version != loaded_version:
                raise StaleDataError(self.schema.name, pk_value)

            self._check_unique(rows, instance, exclude_pk=pk_value)
            self._check_foreign_keys(instance)
            new_version = stored_version + 1
            object.__setattr__(instance, "_tinystore_version", new_version)
            rows[idx] = self._encode(instance)
            self._write_state(state)
            return instance

    def update_many(self, instances: list[T]) -> list[T]:
        if not instances:
            return []
        with self.db._ensure_transaction():
            state = self._read_state()
            rows: list[dict[str, Any]] = state["rows"]
            pk_field = self._pk_field()
            result: list[T] = []
            for instance in instances:
                pk_value = getattr(instance, pk_field)
                idx = self._find_index(rows, pk_value)
                if idx < 0:
                    raise DoesNotExist(
                        f"Cannot update {self.model_cls.__name__} with {pk_field}={pk_value!r}"
                    )
                stored = rows[idx]
                stored_version = stored.get("__version", 0)
                loaded_version = getattr(instance, "_tinystore_version", 0)
                if self.db.optimistic_concurrency and stored_version != loaded_version:
                    raise StaleDataError(self.schema.name, pk_value)
                self._check_unique(rows, instance, exclude_pk=pk_value)
                self._check_foreign_keys(instance)
                object.__setattr__(instance, "_tinystore_version", stored_version + 1)
                rows[idx] = self._encode(instance)
                result.append(instance)
            self._write_state(state)
            return result

    def delete(self, target: object | T) -> int:
        with self.db._ensure_transaction():
            pk_field = self._pk_field()
            pk_value = getattr(target, pk_field) if isinstance(target, self.model_cls) else target
            state = self._read_state()
            if self._find_index(state["rows"], pk_value) < 0:
                raise DoesNotExist(
                    f"Cannot delete {self.model_cls.__name__} with {pk_field}={pk_value!r}"
                )
            self._handle_cascade_on_delete(pk_value)
            state = self._read_state()
            rows = state["rows"]
            idx = self._find_index(rows, pk_value)
            if idx >= 0:
                del rows[idx]
                self._write_state(state)
            return 1

    def delete_many(self, targets: list[object | T]) -> int:
        if not targets:
            return 0
        with self.db._ensure_transaction():
            state = self._read_state()
            rows: list[dict[str, Any]] = state["rows"]
            pk_field = self._pk_field()
            pks_to_delete: list[object] = []
            for target in targets:
                if isinstance(target, self.model_cls):
                    pks_to_delete.append(getattr(target, pk_field))
                else:
                    pks_to_delete.append(target)
            for pk in pks_to_delete:
                if self._find_index(rows, pk) >= 0:
                    self._handle_cascade_on_delete(pk)
            state = self._read_state()
            rows = state["rows"]
            keep: list[dict[str, Any]] = []
            deleted = 0
            for row in rows:
                if row.get(pk_field) in pks_to_delete:
                    deleted += 1
                else:
                    keep.append(row)
            state["rows"] = keep
            self._write_state(state)
            return deleted

    def count(self) -> int:
        with self.db.lock():
            return len(self._read_state()["rows"])

    def save(self, instance: T) -> T:
        pk_field = self._pk_field()
        with self.db._ensure_transaction():
            rows = self._read_state()["rows"]
            pk_value = getattr(instance, pk_field)
            if pk_value is None or self._find_index(rows, pk_value) < 0:
                return self.insert(instance)
            return self.update(instance)

    def ensure_created(self) -> None:
        """Create the table file if missing, with the empty-table skeleton."""
        with self.db._ensure_transaction():
            if not self.db._table_exists(self.schema.name):
                self.db._write_table_state(self.schema.name, dict(EMPTY_TABLE))
