# TinySQL

[![CI](https://github.com/seracoder/tinysql/actions/workflows/ci.yml/badge.svg)](https://github.com/seracoder/tinysql/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

A lightweight, **Pydantic-native** relational database that persists data as
**human-readable JSON files**. No external server, no daemon, no binary format —
just validated models on disk.

TinySQL combines TinyDB-like simplicity with SQLite/ORM relational concepts:
typed Pydantic v2 models, a Pythonic query DSL, unique and foreign-key
constraints, in-memory joins, write-ahead-journaled transactions, and file
locking. It is built for small apps, CLI tools, prototypes, tests, and embedded
datasets — **not** for high-volume or high-concurrency workloads.

---

## 1. Overview

TinySQL turns Pydantic models into database tables backed by JSON files. Each
table is a separate file you can read, diff, and back up with any tool. Data is
validated by Pydantic v2 on the way in and out. A typed query DSL replaces
string interpolation, and a write-ahead journal makes multi-table transactions
all-or-nothing across files.

**Design priorities** (in order): correctness, data integrity, simple API, type
safety, testability, readable implementation, performance.

---

## 2. Installation

TinySQL requires Python 3.11 or newer.

```bash
pip install tinysql
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv add tinysql
```

---

## 3. Quick start

```python
from tinysql import Database, Field, Model


class User(Model):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    email: str = Field(unique=True)
    age: int | None = Field(default=None, index=True)


# A database is just a directory on disk (created if missing).
db = Database("./app_data")
db.register(User)

# Create.
alice = db.insert(User(name="Alice", email="alice@example.com", age=30))
bob = db.insert(User(name="Bob", email="bob@example.com", age=42))

# Read.
print(db.get(User, alice.id))            # by primary key
print(db.all(User))                      # everything

# Update (mutations validate thanks to Pydantic).
alice.age = 31
db.save(alice)

# Delete.
db.delete(alice)
```

---

## 4. Models

A model subclasses `Model` (which itself subclasses `pydantic.BaseModel`) and
declares fields with `Field`:

```python
class Post(Model):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    slug: str = Field(unique=True)
    views: int = Field(default=0, index=True)
    author_id: int = Field(foreign_key="users.id", on_delete="CASCADE")

    class Meta:
        table_name = "posts"   # optional; defaults to a pluralized snake_case name
```

`Field` wraps `pydantic.Field` and attaches TinySQL metadata:

| Keyword         | Default      | Description                                                            |
| --------------- | ------------ | --------------------------------------------------------------------- |
| `primary_key`   | `False`      | Marks the primary key. One per model. Enables auto-increment by default. |
| `autoincrement` | `=primary_key` | Explicitly enable/disable auto-increment for the PK.                 |
| `unique`        | `False`      | Enforces a uniqueness constraint across the table.                    |
| `index`         | `False`      | Builds an in-memory hash index for O(1) eq/in lookups.               |
| `nullable`      | inferred     | Allows `NULL`; fields with a default are nullable.                    |
| `foreign_key`   | `None`       | `"table.column"` reference, validated on write.                       |
| `on_delete`     | `"RESTRICT"` | `"RESTRICT"`, `"CASCADE"`, or `"SET_NULL"`.                           |

Any other keyword arguments (`ge=`, `min_length=`, `description=`, ...) are
forwarded straight to Pydantic, so all of Pydantic's validation works.

### Table naming

By default the table name is derived from the class: `User -> users`,
`Address -> addresses`, `Person -> people`. Override it with a nested `Meta`:

```python
class User(Model):
    ...
    class Meta:
        table_name = "accounts"
```

### Schema evolution

When you reopen a database, TinySQL compares the registered model's schema
against the stored fingerprint. **Additive** changes (new nullable/defaulted
field) are accepted automatically. **Breaking** changes (removed field, type
change) raise `SchemaError`. Use `db.reset_schema()` to discard stored metadata
(destructive — does not delete data files).

---

## 5. CRUD

```python
# Single operations.
db.insert(instance)               # returns the inserted instance (PK assigned)
db.get(Model, pk)                 # raises DoesNotExist if missing
db.get_by(Model, "email", "x@y")  # single-match lookup (uses index if available)
db.all(Model)
db.save(instance)                 # insert-or-update by primary key
db.update(instance)               # update only (checks optimistic-concurrency version)
db.delete(instance)               # by instance ...
db.delete(Model, pk)              # ... or by primary key
db.count(Model)

# Bulk operations (each runs inside one implicit transaction).
db.insert_many([user1, user2, user3])
db.update_many([user1, user2])
db.delete_many(Model, [pk1, pk2, pk3])
```

Every single-op mutation is wrapped as an implicit transaction, so cascading
deletes and other multi-table side effects are all-or-nothing.

---

## 6. Queries

Build queries with `db.select(Model)`. Field comparisons are made against the
model class (e.g. `User.age`), which returns a field proxy that builds an
expression — no magic strings, no `eval`.

```python
young = (
    db.select(User)
    .where(User.age < 35)
    .order_by(User.name)
    .limit(10)
    .all()
)
```

### Operators

| Comparison                | Methods                                                            |
| ------------------------- | ----------------------------------------------------------------- |
| `==`, `!=`, `<`, `<=`, `>`, `>=` | —                                                          |
| membership                | `User.role.in_([...])`, `User.role.not_in([...])`                 |
| strings                   | `.contains(...)`, `.startswith(...)`, `.endswith(...)`            |
| null checks               | `.is_null()`, `.is_not_null()`                                    |
| combine                   | `&` (and), `\|` (or), `~` (not)                                   |

```python
# Compose predicates with & | ~, or pass several to .where(...) (AND-combined).
admins = (
    db.select(User)
    .where(
        (User.age >= 18)
        & User.email.contains("@example.com")
        & User.role.in_(["admin", "editor"])
    )
    .order_by(User.age, desc=True)
    .all()
)
```

### Terminal methods

| Method          | Returns           | Raises                                            |
| --------------- | ----------------- | ------------------------------------------------- |
| `.all()`        | `list[Model]`     |                                                   |
| `.first()`      | `Model \| None`   |                                                   |
| `.one()`        | `Model`           | `DoesNotExist`, `MultipleObjectsReturned`         |
| `.one_or_none()`| `Model \| None`   | `MultipleObjectsReturned`                         |
| `.count()`      | `int`             |                                                   |
| `.exists()`     | `bool`            |                                                   |

`.order_by(field)` is repeatable for multi-key sort; `.limit(n)` and
`.offset(n)` paginate.

### Indexes

Fields declared with `index=True`, `unique=True`, or `primary_key=True` get an
in-memory hash index. Queries with `eq` (`==`) or `in_` conditions on indexed
fields are automatically narrowed via the index instead of scanning all rows.
Indexes are rebuilt from table data on each access — the source of truth is
always the data, never the index.

### Query semantics

- `None` and missing fields are treated as "absent": ordering comparisons
  against `None` return `False`; use `is_null()` / `is_not_null()` explicitly.
- Comparing two non-null values of **incompatible types** (e.g. an `int` field
  against a `str` literal) raises `QueryError` rather than failing silently.
- Results are sorted by `(type_rank, value)`, so mixed types never raise during
  ordering and the output is always deterministic.

---

## 7. Relationships

Relationships are declared with `Relationship(...)` as a field default and loaded
explicitly via `db.related()`. Relationship fields are never persisted — only
the foreign-key column is stored.

```python
from tinysql import Relationship

class Post(Model):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    author_id: int = Field(foreign_key="users.id")
    author: User | None = Relationship(foreign_key="author_id")
```

Load a related object:

```python
post = db.get(Post, 1)
author = db.related(post, "author")    # returns a User instance (or None)
```

The cardinality is inferred from which side holds the FK:
- **many-to-one** (local FK): `db.related(post, "author")` -> single instance or `None`.
- **one-to-many** (remote FK): `db.related(user, "posts")` -> list of instances.

The side is determined automatically from the declared `foreign_key`; if
multiple models reference the same table ambiguously, `RelationshipError` is
raised.

---

## 8. Joins

In-memory INNER and LEFT joins combine two or more registered models. The result
is a list of `Row` objects supporting both positional and attribute access.

```python
rows = (
    db.select(User)
    .join(Post, on=Post.author_id == User.id)
    .where(User.name == "Alice")
    .order_by(Post.title)
    .all()
)
for r in rows:
    print(r.user.name, r.post.title)     # attribute access
    print(r[0], r[1])                    # positional access
```

Join conditions are built by comparing field proxies: `Post.author_id == User.id`
produces a `JoinCondition`. For a LEFT join, unmatched rows contribute `None` on
the right side.

You can chain additional joins and filter on fields from any joined model:

```python
rows = (
    db.select(User)
    .join(Post, on=Post.author_id == User.id)
    .join(Comment, on=Comment.post_id == Post.id, kind="left")
    .where(Post.views > 100)
    .all()
)
```

Joins are evaluated in memory with nested loops — every participating table is
read fully. This is deliberate: TinySQL stores rows as JSON files, so a
disk-efficient join is outside the scope of v1.

---

## 9. Transactions

Group writes so they either all land or all roll back. Transactions acquire the
database-wide write lock for their full duration and buffer all changes in memory.

```python
with db.transaction():
    db.insert(User(name="Carol", email="carol@example.com"))
    db.insert(User(name="Dave", email="dave@example.com"))
# An exception inside the block discards the buffer; no table files are touched.
```

### Write-ahead journal

On commit, the transaction writes a `journal/<txid>.json` file containing the
full new state of every touched table and fsyncs it. That durable write is the
**commit point** — after it succeeds, the transaction is committed even if the
process crashes before all table files are updated. On the next open, recovery
replays any leftover journals idempotently and removes them.

Every single-op mutation (insert, update, delete) runs inside an implicit
transaction via the same code path, so cascading deletes and multi-table side
effects are atomic too.

Nested transactions are not supported and raise `TransactionError`.

### Optimistic concurrency

Each row carries a hidden version number. When you load a row, mutate it, and
call `db.save()` / `db.update()`, TinySQL checks that the stored version still
matches the one you loaded — if another writer got there first, it raises
`StaleDataError`. Disable it with `Database(path, optimistic_concurrency=False)`.

---

## 10. Storage format

A database is a directory. Data is plain JSON you can read, diff, and back up
with any tool:

```
app_data/
├── metadata.json     # version + per-table schema fingerprints + txid counter
├── tinysql.lock      # OS-lock coordination file (its existence is meaningless)
├── journal/          # transaction journals (empty when idle)
└── tables/
    ├── users.json    # {"version": 1, "next_id": 4, "rows": [...]}
    └── posts.json
```

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

All writes use `tempfile -> fsync -> os.replace -> fsync(dir)` — never in-place
mutation. TinySQL never `eval`s, `exec`s, or `pickle`s data; it `json.loads`
into validated Pydantic models and treats the database directory as trusted
local storage. Corrupt JSON produces a clear error instead of silent data loss.

---

## 11. Locking model

Every operation acquires a single **database-wide write lock** with two layers:

1. **In-process**: `threading.RLock` (reentrant, so an active transaction can
   nest operations freely).
2. **Cross-process**: `portalocker` `RLock` on `tinysql.lock` (OS-level file
   locking, so independent processes can safely share one database).

```python
# Hold the lock manually for a custom critical section.
with db.lock(timeout=10.0):
    ...
```

Configure the wait with `Database(path, lock_timeout=...)`; a timeout raises
`LockTimeoutError`. The lock file's existence is **never** treated as the lock —
only a successful `acquire()` matters.

---

## 12. Limitations

- **Single-writer.** One database-wide write lock means no concurrent writes
  within a process or across processes. Readers also acquire the lock, so a
  long-running transaction blocks all other operations.
- **All data in memory.** Tables are loaded fully into Python memory on each
  access. Suitable for thousands to low tens of thousands of rows per table, not
  millions.
- **No query optimizer.** Where-clauses are evaluated in Python. Indexes
  accelerate `eq`/`in_` on indexed fields, but there is no cost-based planner.
- **Single-column constraints.** Primary keys, unique constraints, and indexes
  are single-column only. Composite constraints are on the roadmap.
- **Additive-only schema changes.** Removing a field or changing its type is
  rejected. Use `db.reset_schema()` (destructive) or migrate manually.
- **No network layer.** TinySQL is an embedded library, not a client-server
  database.
- **Trusted local storage.** Data is deserialized with `json.loads` into
  validated Pydantic models, but the database directory is assumed to be under
  your control. Do not expose it to untrusted input.

---

## 13. Roadmap

- **Keyset pagination** (`.keyset(...)`) — non-breaking addition alongside the
  existing `.limit().offset()`.
- **Composite constraints** (multi-column unique / primary key).
- **Persisted indexes** — write index files under `indexes/` and load on open
  instead of rebuilding from data.
- **Query planner improvements** — range scans on indexed fields, join
  reordering.
- **Migration framework** — schema versioning and data migrations.
- **Aggregate queries** — `sum`, `avg`, `min`, `max`, `group_by`.
- **Export/import** — CSV, JSON-lines, and SQLite bridge.

---

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

---

## Errors

All errors inherit from `TinySQLError`:

```
TinySQLError
├── IntegrityError
│   ├── UniqueConstraintError
│   ├── ForeignKeyError
│   └── StaleDataError          # optimistic-concurrency conflict
├── DoesNotExist
├── MultipleObjectsReturned
├── LockTimeoutError
├── TransactionError
├── SchemaError
├── RelationshipError
├── QueryError                  # incompatible-type comparisons, bad expressions
└── StorageError
```

```python
from tinysql import DoesNotExist, UniqueConstraintError

try:
    db.get(User, 999)
except DoesNotExist:
    ...
```

---

## Development

TinySQL uses [uv](https://docs.astral.sh/uv/) for environment and dependency
management, [ruff](https://docs.astral.sh/ruff/) for lint/format, and
[mypy --strict](https://mypy-lang.org/) for types.

```bash
uv sync --dev                       # install dev dependencies
uv run pytest                       # run the test suite
uv run ruff check .                 # lint
uv run ruff format --check .        # format check
uv run mypy                         # strict type check
```

CI runs ruff, mypy, and the full test matrix (Python 3.11 / 3.12 / 3.13 on
Ubuntu, Windows, and macOS) on every push and pull request.

---

## License

[MIT](LICENSE)
