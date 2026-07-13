# Storage format

A database is a directory. Data is plain JSON you can read, diff, and back up
with any tool:

```
app_data/
├── metadata.json     # version + per-table schema fingerprints + txid counter
├── tinystore.lock      # OS-lock coordination file (its existence is meaningless)
├── journal/          # transaction journals (empty when idle)
└── tables/
    ├── users.json    # {"version": 1, "next_id": 4, "rows": [...]}
    └── posts.json
```

## Table files

A table file looks like:

```json
{
  "version": 1,
  "next_id": 2,
  "rows": [
    {"id": 1, "name": "Alice", "email": "alice@example.com", "age": 31, "__version": 2}
  ]
}
```

- `next_id` is the next auto-increment primary key.
- `__version` is the hidden optimistic-concurrency version per row.
- Relationship fields are **never** persisted — only foreign-key columns are.

## Durable writes

All writes use `tempfile -> fsync -> os.replace -> fsync(dir)` — never in-place
mutation. This guarantees that a crash mid-write leaves either the old file or
the complete new file, never a torn write.

## Safety

TinyStore never `eval`s, `exec`s, or `pickle`s data; it `json.loads` into
validated Pydantic models and treats the database directory as trusted local
storage. Corrupt JSON produces a clear error instead of silent data loss.

!!! note "Trusted local storage"
    The database directory is assumed to be under your control. Do not expose it
    to untrusted input — TinyStore is an embedded library, not a hardened server.

## Recovery

On open, TinyStore replays any leftover journals in `journal/` idempotently and
removes them. A committed transaction whose table files were not yet updated is
fully applied before any reads or writes proceed.

## Maintenance

```python
problems = db.check()                          # returns [] when the database is consistent
db.backup("./backups/app_data_snapshot")       # directory snapshot (tables + metadata)
db.reset_schema()                              # destructive: clears stored schema metadata
```

`db.check()` validates that every table file parses, primary keys are unique,
`next_id` exceeds the largest id in use, and registered foreign keys resolve to
existing rows.

`db.backup(target)` copies the database under the lock, excluding the lock file
and journals. The backup is a point-in-time copy that can be opened by a new
`Database` instance.
