# Contacts CLI example

A persistent **contacts manager** you run from the terminal. Each invocation
reopens the same TinyStore directory, so your data survives between runs — the
classic "embedded database for a CLI tool" use case that TinyStore is built
for.

The full source lives at
[`examples/cli_contacts.py`](https://github.com/seracoder/tinystore/blob/main/examples/cli_contacts.py).

---

## Run it

The database lives in `examples/contacts_data/` and accumulates across
invocations. Try a full session:

```bash
python examples/cli_contacts.py add --name "Alice Lee" --email alice@x.dev --tag team --tag eng
python examples/cli_contacts.py add --name "Bob Carr" --email bob@x.dev --phone "555-1234" --tag team
python examples/cli_contacts.py add --name "Carol Ng" --email carol@x.dev

python examples/cli_contacts.py list
python examples/cli_contacts.py search ali
python examples/cli_contacts.py show 1

python examples/cli_contacts.py tag 1 --add vip
python examples/cli_contacts.py list --tag vip

python examples/cli_contacts.py delete 2
python examples/cli_contacts.py stats
```

!!! tip "It's a real app, not a one-shot demo"
    Unlike the [task queue](task-queue.md) and [library](library-catalog.md)
    examples, this one **keeps its data** between runs. Delete
    `examples/contacts_data/` to start fresh.

---

## The model

A single `Contact` model with the field features that make a CLI pleasant:
a **unique, indexed email** for fast lookups, optional fields, and a **`list[str]`**
for tags:

```python
from tinystore import Database, Field, Model

class Contact(Model):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(min_length=1, max_length=100)   # (1)
    email: str = Field(unique=True, index=True)       # (2)
    phone: str | None = None
    notes: str = ""
    tags: list[str] = Field(default_factory=list)     # (3)
```

1. Extra kwargs like `min_length=` / `max_length=` are forwarded straight to
   Pydantic, so validation is free.
2. **`unique=True, index=True`** makes `get_by(Contact, "email", ...)` an
   index lookup and prevents duplicates.
3. **`list[str]`** round-trips through JSON natively — no join table needed for
   simple tags.

---

## Open the database on every run

Each command opens the database, registers the model, does its work, and exits.
This is cheap: TinyStore reopens the directory and re-checks the schema
fingerprint against what's stored on disk.

```python
from pathlib import Path

DB_PATH = Path(__file__).parent / "contacts_data"

def get_db() -> Database:
    db = Database(DB_PATH)
    db.register(Contact)
    return db
```

!!! note "Schema evolution is safe by default"
    When you reopen a database, TinyStore compares the registered model's
    schema against the stored fingerprint. **Additive** changes (a new
    nullable/defaulted field) are accepted automatically; **breaking** changes
    raise `SchemaError`. So adding a field to `Contact` and rerunning the CLI
    just works. See [Models & fields](../guides/models.md).

---

## Add a contact (and handle duplicates)

`unique=True` on `email` turns a duplicate add into a clean
`UniqueConstraintError` you can map to a friendly message:

```python
from tinystore import UniqueConstraintError

def cmd_add(args):
    db = get_db()
    try:
        contact = db.insert(
            Contact(
                name=args.name,
                email=args.email,
                phone=args.phone,
                notes=args.notes,
                tags=list(args.tag or []),
            )
        )
    except UniqueConstraintError:
        print(f"error: a contact with email {args.email!r} already exists", file=sys.stderr)
        return 1
    print(f"added [{contact.id}] {contact.name} <{contact.email}>")
    return 0
```

---

## Search with `contains()`

Build a typed query across multiple fields, combined with `|` (or):

```python
matches = (
    db.select(Contact)
    .where(Contact.name.contains(q) | Contact.email.contains(q))
    .order_by(Contact.name)
    .all()
)
```

!!! info "No magic strings"
    Comparisons go through the model class (`Contact.name.contains(...)`), so
    they're refactor-safe and IDE-friendly. See [Querying](../guides/querying.md).

---

## Mutate, then `save`

Tagging a contact is a load-mutate-save cycle. Because `validate_assignment`
is on, mutating `c.tags` re-validates automatically:

```python
c = db.get(Contact, args.id)
c.tags = sorted((set(c.tags) | set(args.add)) - set(args.remove))
db.save(c)
```

---

## Missing rows are a normal control flow

`db.get()` raises `DoesNotExist` for a missing primary key — catch it and
return a clear error code:

```python
from tinystore import DoesNotExist

try:
    c = db.get(Contact, args.id)
except DoesNotExist:
    print(f"error: no contact with id {args.id}", file=sys.stderr)
    return 1
```

---

## What's on disk

After a session, `examples/contacts_data/` is plain JSON you can read, diff,
or back up with any tool:

```
contacts_data/
├── metadata.json        # schema fingerprint + counters
├── tinystore.lock       # OS-lock coordination file
└── tables/
    └── contacts.json    # {"version": 1, "next_id": 4, "rows": [...]}
```

!!! check "Back it up by copying the directory"
    `db.backup("./my_snapshot")` makes a point-in-time copy under the lock.
    Or just `cp -r contacts_data/ snaps/` — there are no binary formats to
    worry about. See [Storage format](../guides/storage.md).

---

## Recap

This example demonstrated:

- :material-folder-open: **Persistence across invocations** — the CLI use case.
- :material-database-search: **Indexed lookups** (`get_by` on email).
- :material-shield-lock: **Unique constraints** mapped to user-friendly errors.
- :material-text-search: **Text search** with `contains()` and `|`.
- :material-format-list-bulleted: **`list[str]` fields** (tags) stored as JSON.
- :material-sync-alert: **Missing rows** as `DoesNotExist` control flow.

Browse the other examples — the [task queue](task-queue.md) for transactions
and concurrency, or the [library catalog](library-catalog.md) for relationships
and joins.
