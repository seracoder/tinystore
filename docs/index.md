# TinyStore

A lightweight, **Pydantic-native** relational database that persists data as
**human-readable JSON files**. No external server, no daemon, no binary format —
just validated models on disk.

TinyStore combines TinyDB-like simplicity with SQLite/ORM relational concepts:
typed Pydantic v2 models, a Pythonic query DSL, unique and foreign-key
constraints, in-memory joins, write-ahead-journaled transactions, and file
locking. It is built for small apps, CLI tools, prototypes, tests, and embedded
datasets — **not** for high-volume or high-concurrency workloads.

## Why TinyStore?

- :material-file-json-outline: **JSON on disk.** Every table is a separate JSON file you can read,
    diff, and back up with any tool.
- :material-shield-check: **Validated by Pydantic v2.** Data is coerced and validated on the way in
    and out — `ge=`, `min_length=`, custom types, the works.
- :material-database-search: **Typed query DSL.** Field comparisons are made against the model
    class (`User.age < 35`) — no magic strings, no `eval`.
- :material-link-variant: **Relational.** Foreign keys, unique constraints, indexes,
    relationships, and in-memory joins.
- :material-sync: **Atomic transactions.** A write-ahead journal makes multi-table
    transactions all-or-nothing across files.
- :material-lock: **Cross-process safe.** OS-level file locking via `portalocker`.

## Install

```bash
pip install tinystore
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv add tinystore
```

## Quick example

```python
from tinystore import Database, Field, Model


class User(Model):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    email: str = Field(unique=True)
    age: int | None = Field(default=None, index=True)


# A database is just a directory on disk (created if missing).
db = Database("./app_data")
db.register(User)

alice = db.insert(User(name="Alice", email="alice@example.com", age=30))

young = (
    db.select(User)
    .where(User.age < 35)
    .order_by(User.name)
    .all()
)
```

## Where next?

- New to TinyStore? Start with the **[Getting started](getting-started.md)**.
- Learn by feature in the **[Guides](guides/index.md)**.
- Browse every class, method, and exception in the **[API reference](api/index.md)**.
- See it all together in the **[Blog app example](examples/blog-app.md)**.
