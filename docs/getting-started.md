# Getting started

TinyStore turns Pydantic models into database tables backed by JSON files. This
guide takes you from zero to a working app in a few minutes.

## Requirements

TinyStore requires **Python 3.11** or newer.

## Install

```bash
pip install tinystore
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv add tinystore
```

## Your first database

A database is just a directory on disk. Register your models, then insert,
query, update, and delete.

```python
from tinystore import Database, Field, Model


class User(Model):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    email: str = Field(unique=True)
    age: int | None = Field(default=None, index=True)


# Creates ./app_data if it does not exist.
db = Database("./app_data")
db.register(User)

# Create.
alice = db.insert(User(name="Alice", email="alice@example.com", age=30))
bob = db.insert(User(name="Bob", email="bob@example.com", age=42))

# Read.
print(db.get(User, alice.id))   # by primary key
print(db.all(User))             # everything

# Update (mutations validate thanks to Pydantic).
alice.age = 31
db.save(alice)

# Delete.
db.delete(alice)
```

## What just happened?

1. `User` subclasses [`Model`](api/model.md) (which itself subclasses
   `pydantic.BaseModel`). Fields are declared with [`Field`](api/model.md), which
   attaches TinyStore metadata — primary key, unique, index, foreign key — on top
   of Pydantic's own validation.
2. `Database("./app_data")` created a directory. Register the model so TinyStore
   knows about its schema.
3. `insert` assigned an auto-increment primary key, validated the row, and wrote
   it to `app_data/tables/users.json`.

Inspect the directory and you'll see plain JSON:

```
app_data/
├── metadata.json
├── tinystore.lock
└── tables/
    └── users.json    # {"version": 1, "next_id": 3, " "rows": [...]}
```

## Query it

Build queries with `db.select(Model)`. Field comparisons go through the model
class, so they're typed and refactor-safe.

```python
young = (
    db.select(User)
    .where(User.age < 35)
    .order_by(User.name)
    .limit(10)
    .all()
)

# Compose predicates with & | ~.
admins = (
    db.select(User)
    .where(
        (User.age >= 18)
        & User.email.contains("@example.com")
    )
    .all()
)
```

See the **[Querying guide](guides/querying.md)** for the full operator set and
terminal methods (`.first()`, `.one()`, `.count()`, ...).

## Wrap writes in a transaction

```python
with db.transaction():
    db.insert(User(name="Carol", email="carol@example.com"))
    db.insert(User(name="Dave", email="dave@example.com"))
# An exception inside the block discards the buffer; no files are touched.
```

Transactions are atomic across multiple tables via a write-ahead journal. See
the **[Transactions guide](guides/transactions.md)**.

## Errors

All errors inherit from `TinyStoreError`. Catch the specific ones you care about:

```python
from tinystore import DoesNotExist, UniqueConstraintError

try:
    db.get(User, 999)
except DoesNotExist:
    ...
```

Browse the full hierarchy in the **[Exceptions reference](api/exceptions.md)**.

## Next steps

- **[Models & fields](guides/models.md)** — every `Field(...)` keyword.
- **[Relationships](guides/relationships.md)** — `Relationship(...)` and `db.related()`.
- **[Joins](guides/joins.md)** — INNER/LEFT joins across models.
- **[Storage format](guides/storage.md)** — exactly what's on disk.
