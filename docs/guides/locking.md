# Locking model

Every operation acquires a single **database-wide write lock** with two layers:

1. **In-process**: `threading.RLock` (reentrant, so an active transaction can
   nest operations freely).
2. **Cross-process**: `portalocker` `RLock` on `tinystore.lock` (OS-level file
   locking, so independent processes can safely share one database).

```python
# Hold the lock manually for a custom critical section.
with db.lock(timeout=10.0):
    ...
```

## Configuring the wait

Configure the wait with `Database(path, lock_timeout=...)`; a timeout raises
`LockTimeoutError`. The lock file's existence is **never** treated as the lock —
only a successful `acquire()` matters.

```python
from tinystore import Database, LockTimeoutError

try:
    db = Database("./app_data", lock_timeout=5.0)
except LockTimeoutError:
    ...  # another writer held the lock for > 5s during open
```

## What this means

- **Single writer.** One database-wide write lock means no concurrent writes
  within a process or across processes. Readers also acquire the lock, so a
  long-running transaction blocks all other operations.
- **Crash-safe.** Because the lock is an OS-level file lock, a crashed process
  releases it automatically — no "stale lock file" problem.

## Don't rely on the lock file's existence

The `tinystore.lock` file may exist even when no process holds the lock. Always go
through `db.lock(...)` or the implicit locking in each operation. See the
[Transactions guide](transactions.md) for how locking interacts with atomicity.
