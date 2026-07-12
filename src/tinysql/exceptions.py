"""Exception hierarchy for TinySQL.

All errors raised by TinySQL derive from :class:`TinySQLError`, so callers can
catch any database failure with a single ``except`` clause.
"""

from __future__ import annotations


class TinySQLError(Exception):
    """Base class for every TinySQL error."""


class IntegrityError(TinySQLError):
    """A data-integrity constraint was violated."""


class UniqueConstraintError(IntegrityError):
    """A unique constraint would be violated by this write."""

    def __init__(self, table: str, field: str, value: object) -> None:
        self.table = table
        self.field = field
        self.value = value
        super().__init__(f"Unique constraint violated on {table}.{field}={value!r}")


class ForeignKeyError(IntegrityError):
    """A foreign-key reference is invalid or would orphan a row."""


class StaleDataError(IntegrityError):
    """The row was modified by another writer since it was loaded (optimistic concurrency)."""

    def __init__(self, table: str, pk: object) -> None:
        self.table = table
        self.pk = pk
        super().__init__(
            f"Stale write detected for {table} primary key {pk!r}; "
            "the row was modified by another writer. Reload and retry."
        )


class DoesNotExist(TinySQLError):
    """Exactly one row was expected but none was found."""

    def __init__(self, message: str = "Object does not exist") -> None:
        super().__init__(message)


class MultipleObjectsReturned(TinySQLError):
    """Exactly one row was expected but several matched."""

    def __init__(self, message: str = "Multiple objects returned; expected one") -> None:
        super().__init__(message)


class LockTimeoutError(TinySQLError):
    """The lock could not be acquired within the configured timeout."""


class TransactionError(TinySQLError):
    """A transaction was used incorrectly (e.g. nested transactions)."""


class SchemaError(TinySQLError):
    """The on-disk schema is missing, incompatible, or corrupt."""


class QueryError(TinySQLError):
    """A query expression is invalid (e.g. incompatible-type comparison)."""


class RelationshipError(TinySQLError):
    """A relationship could not be resolved (unknown name, ambiguous target, etc.)."""


class StorageError(TinySQLError):
    """The underlying storage layer reported a failure (I/O, corruption)."""


__all__ = [
    "DoesNotExist",
    "ForeignKeyError",
    "IntegrityError",
    "LockTimeoutError",
    "MultipleObjectsReturned",
    "QueryError",
    "RelationshipError",
    "SchemaError",
    "StaleDataError",
    "StorageError",
    "TinySQLError",
    "TransactionError",
    "UniqueConstraintError",
]
