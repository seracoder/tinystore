"""The :class:`Database` — TinySQL's main entry point.

A database is a directory on disk. Tables live as separate JSON files, metadata
in ``metadata.json``, locking via ``tinysql.lock``. Register Pydantic-based
models, then insert / query / update / delete.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from .exceptions import RelationshipError, SchemaError
from .locking import FileLockManager, LockHandle, LockManager
from .model import Model
from .schema import METADATA_VERSION, TableSchema, classify_change
from .serialization import EMPTY_TABLE
from .storage.json import JsonStorage
from .table import Table, _parse_fk

if TYPE_CHECKING:
    from .transaction import Transaction

__all__ = ["Database"]

logger = logging.getLogger("tinysql")


class Database:
    """A TinySQL database rooted at a filesystem directory.

    Parameters
    ----------
    path:
        Database directory. Created if missing.
    lock_timeout:
        Seconds to wait for the database-wide lock before raising
        :class:`~tinysql.exceptions.LockTimeoutError`.
    optimistic_concurrency:
        If ``True`` (default), writes check a hidden row version and raise
        :class:`~tinysql.exceptions.StaleDataError` on stale updates.
    debug:
        Enable debug logging.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        lock_timeout: float = 30.0,
        optimistic_concurrency: bool = True,
        debug: bool = False,
        storage: JsonStorage | None = None,
        lock_manager: LockManager | None = None,
    ) -> None:
        self._storage = storage if storage is not None else JsonStorage(Path(path))
        self._lock_manager = (
            lock_manager
            if lock_manager is not None
            else FileLockManager(self._storage.lock_file, default_timeout=lock_timeout)
        )
        self.optimistic_concurrency = optimistic_concurrency
        self.debug = debug
        if debug:
            logging.basicConfig(level=logging.DEBUG)
            logger.setLevel(logging.DEBUG)

        self._registry: dict[str, type[Model]] = {}
        self._schemas: dict[str, TableSchema] = {}
        self._tables: dict[str, Table[Any]] = {}

        # Active transaction (Phase 5). None when no transaction is active.
        self._active_transaction: Transaction | None = None

        # Recover any incomplete transactions before serving.
        self._recover()

    # ---- properties ----
    @property
    def root(self) -> Path:
        return self._storage.root

    @property
    def storage(self) -> JsonStorage:
        return self._storage

    # ---- locking ----
    @contextmanager
    def lock(self, *, timeout: float | None = None) -> Iterator[LockHandle]:
        """Acquire the database-wide write lock for the duration of the block."""
        handle = self._lock_manager.acquire(timeout=timeout)
        try:
            yield handle
        finally:
            handle.release()

    # ---- state access (storage or transaction buffer) ----
    def _read_table_state(self, name: str) -> dict[str, Any]:
        if self._active_transaction is not None:
            return self._active_transaction.read_state(name)
        return self._storage.read_table(name)

    def _write_table_state(self, name: str, data: dict[str, Any]) -> None:
        if self._active_transaction is not None:
            self._active_transaction.write_state(name, data)
            return
        # Phase 1: direct atomic write per single op.
        self._storage.write_table(name, data)

    def _table_exists(self, name: str) -> bool:
        if self._active_transaction is not None:
            return self._active_transaction.has_table(name)
        return self._storage.table_exists(name)

    # ---- registration ----
    def register(self, model_cls: type[Model]) -> type[Model]:
        """Register a model class with this database.

        Creates its table file if missing, validates schema compatibility with
        any previously-persisted schema, and updates ``metadata.json``.
        """
        schema = model_cls.__tinysql_schema__
        name = schema.name
        with self.lock():
            metadata = self._load_metadata()
            existing = metadata["tables"].get(name)
            if existing is not None:
                stored = TableSchema.from_dict(existing)
                changes = classify_change(stored, schema)
                breaking = [c for c in changes if c.kind == "breaking"]
                if breaking:
                    details = "; ".join(c.detail for c in breaking)
                    raise SchemaError(
                        f"Incompatible schema change for table {name!r}: {details}. "
                        "Use db.reset_schema() to discard stored data, or migrate manually."
                    )
                logger.debug(
                    "Schema change accepted for %s: %s",
                    name,
                    "; ".join(c.detail for c in changes) or "no-op",
                )

            metadata["tables"][name] = schema.to_dict()
            self._save_metadata(metadata)

            self._registry[name] = model_cls
            self._schemas[name] = schema
            # Reset the cached Table so it picks up the new schema.
            self._tables.pop(name, None)

            # Ensure the table file exists on disk.
            if not self._storage.table_exists(name):
                self._storage.write_table(name, dict(EMPTY_TABLE))
            elif self._active_transaction is None:
                # Ensure on-disk table is loadable (catches corruption early).
                self._storage.read_table(name)

        # Best-effort rebuild of forward references.
        self._rebuild_model_refs(model_cls)
        logger.debug("Registered %s -> table %s", model_cls.__name__, name)
        return model_cls

    def _rebuild_model_refs(self, model_cls: type[Model]) -> None:
        try:
            model_cls.model_rebuild(force=True)
        except Exception as exc:  # pragma: no cover - forward-ref issues are non-fatal here
            logger.debug("model_rebuild deferred for %s: %s", model_cls.__name__, exc)

    def table(self, model_cls: type[Model]) -> Table[Any]:
        schema = model_cls.__tinysql_schema__
        name = schema.name
        if name not in self._registry:
            raise SchemaError(f"Model {model_cls.__name__!r} is not registered with this database")
        cached = self._tables.get(name)
        if cached is not None:
            return cached
        tbl = Table(self, model_cls)
        self._tables[name] = tbl
        return tbl

    # ---- metadata persistence ----
    def _load_metadata(self) -> dict[str, Any]:
        data = self._storage.read_metadata()
        if data is None:
            return {"version": METADATA_VERSION, "next_txid": 1, "tables": {}}
        if data.get("version") != METADATA_VERSION:
            raise SchemaError(
                f"Unsupported metadata version {data.get('version')!r}; expected {METADATA_VERSION}"
            )
        data.setdefault("tables", {})
        data.setdefault("next_txid", 1)
        return data

    def _save_metadata(self, data: dict[str, Any]) -> None:
        self._storage.write_metadata(data)

    def reset_schema(self) -> None:
        """Discard all stored schema metadata (destructive — does NOT delete data)."""
        with self.lock():
            self._save_metadata({"version": METADATA_VERSION, "next_txid": 1, "tables": {}})
            self._registry.clear()
            self._schemas.clear()
            self._tables.clear()

    # ---- convenience CRUD dispatch ----
    def insert(self, instance: Model) -> Model:
        return cast(Model, self.table(type(instance)).insert(instance))

    def insert_many(self, instances: list[Model]) -> list[Model]:
        if not instances:
            return []
        return cast(list[Model], self.table(type(instances[0])).insert_many(instances))

    def get(self, model_cls: type[Model], pk: object) -> Model:
        return cast(Model, self.table(model_cls).get(pk))

    def get_by(self, model_cls: type[Model], field: str, value: object) -> Model:
        return cast(Model, self.table(model_cls).get_by(field, value))

    def all(self, model_cls: type[Model]) -> list[Model]:
        return cast(list[Model], self.table(model_cls).all())

    def save(self, instance: Model) -> Model:
        return cast(Model, self.table(type(instance)).save(instance))

    def update(self, instance: Model) -> Model:
        return cast(Model, self.table(type(instance)).update(instance))

    def update_many(self, instances: list[Model]) -> list[Model]:
        if not instances:
            return []
        return cast(list[Model], self.table(type(instances[0])).update_many(instances))

    def delete(self, target: Model | type[Model], pk: object | None = None) -> int:
        if isinstance(target, type) and issubclass(target, Model):
            if pk is None:
                raise TypeError("delete(model_cls, pk) requires a primary key")
            return self.table(target).delete(pk)
        return self.table(type(target)).delete(target)

    def delete_many(self, model_cls: type[Model], pks: list[object]) -> int:
        return self.table(model_cls).delete_many(pks)

    def count(self, model_cls: type[Model]) -> int:
        return self.table(model_cls).count()

    # ---- transaction (Phase 5) ----
    def transaction(self, *, timeout: float | None = None) -> Any:
        from .transaction import Transaction

        return Transaction(self, timeout=timeout)

    # ---- query (Phase 2) ----
    def select(self, model_cls: type[Model]) -> Any:
        from .query import SelectQuery

        # Ensure registered (raises clear error otherwise).
        self.table(model_cls)
        return SelectQuery(self, model_cls)

    # ---- relationships (Phase 3) ----
    def related(self, obj: Model, name: str) -> Any:
        """Explicitly load a related model or list of models for a relationship.

        For a many-to-one / one-to-one relationship (the FK lives on this side)
        returns a single instance, or ``None`` when the FK is null or the
        referenced row is gone. For a one-to-many relationship (the FK lives on
        the related side) returns a list of instances.

        The side is inferred from the declared ``foreign_key``: if it names a
        local FK field, this is the "one" end (follow the FK to its parent);
        otherwise the related model is found by scanning registered models for
        one whose field named ``foreign_key`` points back at this table.
        """
        model_cls = type(obj)
        schema = model_cls.__tinysql_schema__
        rel = next((r for r in schema.relationships if r[0] == name), None)
        if rel is None:
            raise RelationshipError(
                f"{model_cls.__name__} has no relationship named {name!r}"
            )
        fk_field_name = rel[1]

        local_field = schema.field(fk_field_name)
        if local_field is not None and local_field.foreign_key:
            return self._load_related_one(obj, fk_field_name, local_field.foreign_key)
        return self._load_related_many(obj, schema, fk_field_name)

    def _load_related_one(
        self, obj: Model, fk_field_name: str, fk_ref: str
    ) -> Model | None:
        ref_table, ref_column = _parse_fk(fk_ref)
        fk_value = getattr(obj, fk_field_name)
        if fk_value is None:
            return None
        target_cls = self._registry.get(ref_table)
        if target_cls is None:
            raise RelationshipError(
                f"Relationship via {fk_field_name!r} targets unregistered table "
                f"{ref_table!r}"
            )
        matches = self.table(target_cls).find(ref_column, fk_value)
        return matches[0] if matches else None

    def _load_related_many(
        self, obj: Model, schema: TableSchema, fk_field_name: str
    ) -> list[Model]:
        this_table = schema.name
        candidates: list[type[Model]] = []
        for tname, target_cls in self._registry.items():
            if tname == this_table:
                continue
            tf = target_cls.__tinysql_schema__.field(fk_field_name)
            if tf is not None and tf.foreign_key:
                ref_table, _ = _parse_fk(tf.foreign_key)
                if ref_table == this_table:
                    candidates.append(target_cls)
        if not candidates:
            raise RelationshipError(
                f"No registered model has a foreign key {fk_field_name!r} targeting "
                f"{this_table!r}; cannot resolve one-to-many relationship"
            )
        if len(candidates) > 1:
            names = ", ".join(c.__name__ for c in candidates)
            raise RelationshipError(
                f"Ambiguous relationship: multiple models ({names}) declare "
                f"{fk_field_name!r} targeting {this_table!r}; disambiguate with "
                "Relationship(to=...)"
            )
        target_cls = candidates[0]
        this_pk = schema.primary_key.name
        pk_value = getattr(obj, this_pk)
        return self.table(target_cls).find(fk_field_name, pk_value)

    # ---- recovery (Phase 5 stub) ----
    def _recover(self) -> None:
        """Replay any leftover transaction journals found on open."""
        journals = self._storage.list_journals()
        if not journals:
            return
        logger.warning("Found %d unfinished transaction(s); recovering.", len(journals))
        for txid in journals:
            try:
                journal = self._storage.read_journal(txid)
                tables = journal.get("tables", {})
                for table_name, state in tables.items():
                    self._storage.write_table(table_name, state)
            except Exception as exc:
                logger.error("Failed to recover journal %s: %s", txid, exc)
                raise
            finally:
                self._storage.remove_journal(txid)

    # ---- introspection / maintenance ----
    def check(self) -> list[str]:
        """Validate on-disk state. Returns a list of problem descriptions.

        An empty list means the database is consistent. Problems are also
        logged. Raises :class:`~tinysql.exceptions.TinySQLError` for the first
        hard failure (e.g. corrupt JSON).
        """
        problems: list[str] = []
        with self.lock():
            for name in self._storage.list_tables():
                try:
                    state = self._storage.read_table(name)
                except Exception as exc:
                    problems.append(f"table {name!r}: unreadable ({exc})")
                    continue
                rows = state.get("rows", [])
                pk_field = None
                if name in self._schemas:
                    pk_field = self._schemas[name].primary_key.name
                seen: set[object] = set()
                for row in rows:
                    if pk_field is not None:
                        pkv = row.get(pk_field)
                        if pkv in seen:
                            problems.append(f"table {name!r}: duplicate primary key {pkv!r}")
                        seen.add(pkv)
                next_id = state.get("next_id", 1)
                max_id = max((r.get(pk_field, 0) for r in rows), default=0) if pk_field else 0
                if pk_field and next_id <= max_id:
                    problems.append(f"table {name!r}: next_id {next_id} <= max id {max_id}")
        if problems:
            for p in problems:
                logger.warning("check(): %s", p)
        return problems

    def backup(self, target: str | Path) -> Path:
        """Snapshot the database (excluding the lock file and journals)."""
        target_path = Path(target)
        with self.lock():
            self._storage.snapshot(target_path)
        return target_path

    # ---- internal: allocate transaction ids ----
    def _next_txid(self) -> str:
        # Phase 1: not yet wired into metadata; use a random suffix for uniqueness.
        return secrets.token_hex(8)
