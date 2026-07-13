"""JSON file storage backend.

Layout::

    <root>/
      metadata.json
      tinystore.lock
      journal/<txid>.json
      tables/<name>.json

Each table is its own JSON file. Writes are atomic: data is serialized to a
temporary file in the same directory, flushed and fsync'd, then ``os.replace``'d
into place, followed by a best-effort parent-directory fsync.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sys
from pathlib import Path
from typing import Any, cast

from ..exceptions import StorageError
from ..serialization import dumps, loads
from .base import StorageBackend

__all__ = ["JsonStorage"]


class JsonStorage(StorageBackend):
    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        (self._root / "tables").mkdir(parents=True, exist_ok=True)
        (self._root / "journal").mkdir(parents=True, exist_ok=True)
        # The lock coordination file is touched so it exists on disk. NOTE:
        # existence is meaningless for locking; only an acquired OS handle
        # denotes ownership.
        self._lock_path = self._root / "tinystore.lock"
        self._lock_path.touch(exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    @property
    def lock_file(self) -> Path:
        return self._lock_path

    @property
    def tables_dir(self) -> Path:
        return self._root / "tables"

    @property
    def journal_dir(self) -> Path:
        return self._root / "journal"

    @property
    def metadata_file(self) -> Path:
        return self._root / "metadata.json"

    # ---- atomic write primitive ----
    def _atomic_write_text(self, target: Path, text: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, target)
            self.fsync_dir(target.parent)
        except Exception:
            with contextlib.suppress(Exception):
                tmp.unlink(missing_ok=True)
            raise

    def fsync_dir(self, path: Path) -> None:
        if sys.platform == "win32":
            return  # directory fsync not supported on Windows
        try:
            fd = os.open(str(path), os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError:
            pass
        finally:
            os.close(fd)

    # ---- tables ----
    def table_path(self, name: str) -> Path:
        return self.tables_dir / f"{name}.json"

    def read_table(self, name: str) -> dict[str, Any]:
        path = self.table_path(name)
        if not path.exists():
            raise StorageError(f"Table {name!r} does not exist at {path}")
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise StorageError(f"Could not read table {name!r}: {exc}") from exc
        try:
            data = cast(dict[str, Any], loads(text))
        except ValueError as exc:
            raise StorageError(f"Table {name!r} at {path} contains corrupt JSON: {exc}") from exc
        if not isinstance(data, dict) or "rows" not in data:
            raise StorageError(f"Table {name!r} at {path} is malformed (missing 'rows')")
        return data

    def write_table(self, name: str, data: dict[str, Any]) -> None:
        self._atomic_write_text(self.table_path(name), dumps(data))

    def table_exists(self, name: str) -> bool:
        return self.table_path(name).exists()

    def list_tables(self) -> list[str]:
        if not self.tables_dir.exists():
            return []
        return sorted(p.stem for p in self.tables_dir.glob("*.json"))

    def delete_table(self, name: str) -> None:
        self.table_path(name).unlink(missing_ok=True)

    # ---- metadata ----
    def read_metadata(self) -> dict[str, Any] | None:
        if not self.metadata_file.exists():
            return None
        try:
            text = self.metadata_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise StorageError(f"Could not read metadata: {exc}") from exc
        try:
            data = cast(dict[str, Any], loads(text))
        except ValueError as exc:
            raise StorageError(f"metadata.json is corrupt: {exc}") from exc
        return data

    def write_metadata(self, data: dict[str, Any]) -> None:
        self._atomic_write_text(self.metadata_file, dumps(data))

    # ---- journal ----
    def journal_path(self, txid: str) -> Path:
        return self.journal_dir / f"{txid}.json"

    def write_journal(self, txid: str, data: dict[str, Any]) -> Path:
        path = self.journal_path(txid)
        self._atomic_write_text(path, dumps(data))
        return path

    def list_journals(self) -> list[str]:
        if not self.journal_dir.exists():
            return []
        return sorted(p.stem for p in self.journal_dir.glob("*.json"))

    def read_journal(self, txid: str) -> dict[str, Any]:
        path = self.journal_path(txid)
        try:
            return cast(dict[str, Any], loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            raise StorageError(f"Corrupt journal {txid!r}: {exc}") from exc

    def remove_journal(self, txid: str) -> None:
        self.journal_path(txid).unlink(missing_ok=True)

    # ---- backup ----
    def snapshot(self, target: Path) -> None:
        target = Path(target)
        target.mkdir(parents=True, exist_ok=False)
        for sub in ("tables",):
            (target / sub).mkdir(exist_ok=True)
        if self.metadata_file.exists():
            shutil.copy2(self.metadata_file, target / "metadata.json")
        for tp in self.tables_dir.glob("*.json"):
            shutil.copy2(tp, target / "tables" / tp.name)
