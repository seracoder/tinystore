"""Locking for TinySQL.

Two layers, behind a single :class:`LockManager` abstraction:

* Layer 1: an in-process :class:`threading.RLock` (reentrant within the process).
* Layer 2: an inter-process OS-level file lock on ``tinysql.lock`` using
  ``portalocker``.

**Important**: the mere existence of the ``tinysql.lock`` file does *not* imply
that a lock is held. Only a successful ``acquire()`` call on the OS handle
constitutes ownership of the lock. The file may persist on disk after use; that
is harmless.
"""

from __future__ import annotations

import abc
import threading
from pathlib import Path
from typing import ClassVar

import portalocker

from .exceptions import LockTimeoutError

__all__ = ["FileLockManager", "LockHandle", "LockManager"]


class LockHandle(abc.ABC):
    """An acquired lock. Releasing is mandatory."""

    @abc.abstractmethod
    def release(self) -> None: ...

    def __enter__(self) -> LockHandle:
        return self

    def __exit__(self, *_: object) -> None:
        self.release()


class LockManager(abc.ABC):
    """Abstraction over the database-wide write lock."""

    @abc.abstractmethod
    def acquire(self, *, timeout: float | None = None) -> LockHandle:
        """Acquire the lock, raising :class:`LockTimeoutError` on timeout."""

    def __call__(self, *, timeout: float | None = None) -> LockHandle:
        return self.acquire(timeout=timeout)


class _ThreadAndFileHandle(LockHandle):
    """Releases the thread RLock and the inter-process file lock."""

    def __init__(
        self,
        thread_lock: threading.RLock,
        file_lock: portalocker.RLock,
        file_handle: object,
    ) -> None:
        self._thread_lock = thread_lock
        self._file_lock = file_lock
        self._file_handle = file_handle
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        try:
            self._file_lock.release()
        finally:
            self._thread_lock.release()


class FileLockManager(LockManager):
    """Default :class:`LockManager` using ``threading.RLock`` + portalocker.

    Reentrant within a single process (the RLock allows the same thread to
    acquire multiple times). Across processes, portalocker provides the OS-level
    mutual exclusion.

    The in-process ``RLock`` is shared across all :class:`FileLockManager`
    instances that point at the same lock path, so two :class:`Database` objects
    opened on the same directory within one process are still mutually excluded.
    """

    # Shared, per-resolved-path in-process locks.
    _thread_locks: ClassVar[dict[str, threading.RLock]] = {}
    _thread_locks_guard: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self, lock_file: Path, *, default_timeout: float = 30.0) -> None:
        self._lock_file = lock_file
        self._default_timeout = default_timeout
        self._thread_lock = self._shared_thread_lock(lock_file)
        # portalocker.RLock is reentrant within the same thread for the same path.
        self._file_lock = portalocker.RLock(str(lock_file), fail_when_locked=False)

    @classmethod
    def _shared_thread_lock(cls, lock_file: Path) -> threading.RLock:
        key = str(lock_file.resolve())
        with cls._thread_locks_guard:
            lock = cls._thread_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                cls._thread_locks[key] = lock
            return lock

    def acquire(self, *, timeout: float | None = None) -> LockHandle:
        wait = self._default_timeout if timeout is None else timeout
        # Layer 1: in-process reentrant lock. Blocks other threads in THIS process.
        # ``wait is None`` means block indefinitely.
        if wait is None:
            got_thread = self._thread_lock.acquire()
        else:
            got_thread = self._thread_lock.acquire(timeout=max(wait, 0.0))
        if not got_thread:
            raise LockTimeoutError(
                f"Could not acquire in-process lock {self._lock_file} within {wait}s"
            )
        try:
            try:
                file_handle = self._file_lock.acquire(timeout=wait)
            except portalocker.exceptions.LockException as exc:
                raise LockTimeoutError(
                    f"Could not acquire database lock {self._lock_file} within {wait}s: {exc}"
                ) from exc
            return _ThreadAndFileHandle(self._thread_lock, self._file_lock, file_handle)
        except BaseException:
            self._thread_lock.release()
            raise
