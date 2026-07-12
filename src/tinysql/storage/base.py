"""Storage backend abstraction.

TinySQL talks to on-disk storage exclusively through :class:`StorageBackend`.
The query engine never performs filesystem operations. Today the only backend
is :class:`~tinysql.storage.json.JsonStorage`; the abstraction exists so that
alternative backends (e.g. a single-file or memory backend for tests) can be
plugged in later.
"""

from __future__ import annotations

import abc
from pathlib import Path
from typing import Any

__all__ = ["StorageBackend"]


class StorageBackend(abc.ABC):
    """Reads and writes tables, metadata, and journals."""

    @property
    @abc.abstractmethod
    def root(self) -> Path:
        """Database root directory."""

    @property
    @abc.abstractmethod
    def lock_file(self) -> Path:
        """Path to the OS lock coordination file."""

    # ---- tables ----
    @abc.abstractmethod
    def read_table(self, name: str) -> dict[str, Any]:
        """Read a table document (``{version, next_id, rows}``).

        Raises :class:`~tinysql.exceptions.TinySQLError` if the file is missing
        or corrupt.
        """

    @abc.abstractmethod
    def write_table(self, name: str, data: dict[str, Any]) -> None:
        """Atomically write a table document."""

    @abc.abstractmethod
    def table_exists(self, name: str) -> bool: ...

    @abc.abstractmethod
    def list_tables(self) -> list[str]: ...

    @abc.abstractmethod
    def delete_table(self, name: str) -> None: ...

    # ---- metadata ----
    @abc.abstractmethod
    def read_metadata(self) -> dict[str, Any] | None: ...

    @abc.abstractmethod
    def write_metadata(self, data: dict[str, Any]) -> None: ...

    # ---- journal (Phase 5) ----
    @abc.abstractmethod
    def write_journal(self, txid: str, data: dict[str, Any]) -> Path: ...

    @abc.abstractmethod
    def list_journals(self) -> list[str]: ...

    @abc.abstractmethod
    def read_journal(self, txid: str) -> dict[str, Any]: ...

    @abc.abstractmethod
    def remove_journal(self, txid: str) -> None: ...

    @abc.abstractmethod
    def fsync_dir(self, path: Path) -> None: ...

    # ---- backup ----
    @abc.abstractmethod
    def snapshot(self, target: Path) -> None: ...
