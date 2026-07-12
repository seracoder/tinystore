"""Transactions.

A transaction acquires the database-wide write lock for its full duration and
buffers all modified table states in memory. On commit it flushes every touched
table atomically; on rollback it discards the buffer and no table files are
touched.

Phase 1 provides basic transactions: each touched table file is written
atomically on commit, but a crash *between* those writes can leave the database
partially updated. Phase 5 adds a write-ahead journal that makes commit
all-or-nothing across multiple table files.

Nested transactions are not supported and raise :class:`TransactionError`.
"""

from __future__ import annotations

import copy
import logging
from typing import TYPE_CHECKING, Any

from .exceptions import TransactionError

if TYPE_CHECKING:
    from .database import Database

logger = logging.getLogger("tinysql")


class Transaction:
    """A simple in-memory transaction with copy-on-first-touch buffering."""

    def __init__(self, database: Database, *, timeout: float | None = None) -> None:
        self.db = database
        self.timeout = timeout
        self._buffer: dict[str, dict[str, Any]] = {}
        self._entered = False
        self._lock_handle: Any = None

    # ---- buffer API used by Database._read_table_state / _write_table_state ----
    def read_state(self, name: str) -> dict[str, Any]:
        if name not in self._buffer:
            # Copy-on-first-touch so the buffer is isolated from later storage changes.
            state = self.db.storage.read_table(name)
            self._buffer[name] = copy.deepcopy(state)
        return self._buffer[name]

    def write_state(self, name: str, data: dict[str, Any]) -> None:
        self._buffer[name] = copy.deepcopy(data)

    def has_table(self, name: str) -> bool:
        return name in self._buffer or self.db.storage.table_exists(name)

    # ---- context manager ----
    def __enter__(self) -> Transaction:
        if self.db._active_transaction is not None:
            raise TransactionError(
                "Nested transactions are not supported. "
                "Reuse the outer transaction or restructure your code."
            )
        self._lock_handle = self.db._lock_manager.acquire(timeout=self.timeout)
        self.db._active_transaction = self
        self._entered = True
        logger.debug("transaction BEGIN")
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        try:
            if exc is None:
                self._commit()
            else:
                self._rollback()
        finally:
            self.db._active_transaction = None
            self._entered = False
            if self._lock_handle is not None:
                self._lock_handle.release()
                self._lock_handle = None
        return None

    def _commit(self) -> None:
        for name, state in self._buffer.items():
            self.db.storage.write_table(name, state)
        logger.debug("transaction COMMIT (%d tables)", len(self._buffer))
        self._buffer.clear()

    def _rollback(self) -> None:
        logger.debug("transaction ROLLBACK (%d tables discarded)", len(self._buffer))
        self._buffer.clear()
