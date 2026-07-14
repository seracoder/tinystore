# Library catalog example

A small **library**: authors, books, members, and loans. This example exercises
the relational side of TinyStore end to end — **relationships**, **joins**,
**unique constraints**, finding rows with missing values, **predicate
composition**, and every `on_delete` behavior.

The full source lives at
[`examples/library_catalog.py`](https://github.com/seracoder/tinystore/blob/main/examples/library_catalog.py).

---

## Run it

```bash
python examples/library_catalog.py
```

The script starts from a clean slate each run (it removes its own
`library_data/` directory first).

---

## Define the models

Four models, three foreign-key relationships:

```python
from tinystore import (
    Database,
    Field,
    ForeignKeyError,
    Model,
    Relationship,
    UniqueConstraintError,
)


class Author(Model):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    country: str = ""


class Book(Model):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    isbn: str = Field(unique=True)                       # (1)
    year: int = Field(default=0, index=True)
    author_id: int = Field(foreign_key="authors.id")     # (2) RESTRICT (default)
    author: Author | None = Relationship(foreign_key="author_id")  # (3)


class Member(Model):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    email: str = Field(unique=True, index=True)


class Loan(Model):
    id: int | None = Field(default=None, primary_key=True)
    book_id: int = Field(foreign_key="books.id", on_delete="CASCADE")    # (4)
    member_id: int = Field(foreign_key="members.id", on_delete="CASCADE")
    borrowed_on: str
    returned_on: str | None = None                                       # (5)
```

1. **`unique=True`** on `isbn` enforces no two books share an ISBN.
2. `Book.author_id` uses the **default `RESTRICT`** — you cannot delete an
   author who still has books.
3. **`Relationship(foreign_key="author_id")`** declares the many-to-one side;
   load it with `db.related(book, "author")`.
4. `Loan.book_id` and `Loan.member_id` use **`CASCADE`** — deleting a book or
   member removes their loans.
5. `returned_on: str | None` lets a loan be "open" (`None`) or "returned".

---

## Seed the catalog

```python
with db.transaction():
    tolkien = db.insert(Author(name="J.R.R. Tolkien", country="UK"))
    orwell = db.insert(Author(name="George Orwell", country="UK"))
    gibson = db.insert(Author(name="William Gibson", country="USA"))

    db.insert(Book(title="The Hobbit", isbn="978-0261102217", year=1937, author_id=tolkien.id))
    db.insert(Book(title="1984", isbn="978-0451524935", year=1949, author_id=orwell.id))
    db.insert(Book(title="Neuromancer", isbn="978-0441569595", year=1984, author_id=gibson.id))

    alice = db.insert(Member(name="Alice", email="alice@library.dev"))
    db.insert(Member(name="Bob", email="bob@library.dev"))

    db.insert(Loan(book_id=1, member_id=alice.id, borrowed_on="2024-01-10"))
    db.insert(Loan(book_id=2, member_id=alice.id, borrowed_on="2024-02-01", returned_on="2024-02-10"))
    db.insert(Loan(book_id=3, member_id=2, borrowed_on="2024-03-15"))
```

---

## Unique constraints catch duplicates

A second book with an existing ISBN is rejected before it touches disk:

```python
try:
    db.insert(Book(title="The Hobbit (dup)", isbn="978-0261102217", year=1937, author_id=1))
except UniqueConstraintError as exc:
    print(exc)   # Unique constraint violated on books.isbn='978-0261102217'
```

---

## Many-to-one: book &rarr; author

Follow the declared `Relationship` with `db.related()`:

```python
for book in db.select(Book).order_by(Book.title).all():
    author = db.related(book, "author")
    print(f"'{book.title}' ({book.year}) by {author.name}")
```

---

## One-to-many: author &rarr; books

You can declare a reverse `Relationship` on the parent, but for a quick
traversal a **direct query** is often clearer — and avoids a forward-reference
cycle between the two models:

```python
for author in db.select(Author).order_by(Author.name).all():
    books = db.select(Book).where(Book.author_id == author.id).order_by(Book.year).all()
    print(f"{author.name}: {', '.join(b.title for b in books)}")
```

!!! tip "Relationship vs. query"
    Use `db.related()` when you have a clear parent and want to follow one FK.
    Use a **query** (or a **join**, below) when you want to combine or filter
    rows from multiple tables. See [Relationships](../guides/relationships.md).

---

## Three-table join: who borrowed what?

Chain `.join(...)` to walk `Member &rarr; Loan &rarr; Book` in one result set.
Each row exposes every joined model as an attribute:

```python
rows = (
    db.select(Member)
    .join(Loan, on=Loan.member_id == Member.id)
    .join(Book, on=Book.id == Loan.book_id)
    .order_by(Member.name)
    .all()
)
for r in rows:
    status = "returned" if r.loan.returned_on else "on loan"
    print(f"{r.member.name} borrowed '{r.book.title}' ({status})")
```

!!! info "Joins run in memory"
    TinyStore evaluates joins with nested loops over the participating tables.
    That's perfect for thousands of rows; for millions, export to SQLite or an
    OLAP engine. See [Joins](../guides/joins.md).

---

## Find open loans with `is_null()`

`None` (and missing) values are "absent" — use `is_null()` / `is_not_null()`
rather than `== None`:

```python
open_loans = db.select(Loan).where(Loan.returned_on.is_null()).all()
```

---

## Compose predicates with `& | ~`

Combine expressions to express any boolean. Here, *Alice's open loans* **or**
*anything borrowed in March 2024*:

```python
expr = (
    (Loan.member_id == 1) & Loan.returned_on.is_null()
) | Loan.borrowed_on.startswith("2024-03")

for loan in db.select(Loan).where(expr).all():
    print(loan)
```

!!! note "Operator reference"
    `&` is **and**, `|` is **or**, `~` is **not**. You can also pass several
    expressions to a single `.where(...)` (they're AND-combined). See the full
    operator table in [Querying](../guides/querying.md).

---

## `on_delete` in action

**`CASCADE`** — deleting a book removes its loans:

```python
print(db.count(Loan))      # -> 3
db.delete(Book, 2)         # '1984' had a (returned) loan
print(db.count(Loan))      # -> 2
```

**`RESTRICT`** (the default) — deleting an author who still has books is
blocked:

```python
try:
    db.delete(Author, 1)   # Tolkien still has 'The Hobbit'
except ForeignKeyError as exc:
    print(exc)   # Cannot delete authors 1: row(s) in books.author_id reference it
```

!!! summary "The three behaviors"
    | `on_delete` | When the referenced row is deleted...            |
    | ----------- | ------------------------------------------------- |
    | `RESTRICT`  | raise `ForeignKeyError` if dependents exist.      |
    | `CASCADE`   | delete the dependent rows too.                    |
    | `SET_NULL`  | null out the FK on the dependents (must be nullable). |

---

## Recap

This example demonstrated:

- :material-link-variant: **Many-to-one** relationships via `db.related()`.
- :material-format-list-bulleted: **One-to-many** via a direct query.
- :material-table-multiple: **Three-table joins** across `Member &rarr; Loan &rarr; Book`.
- :material-shield-lock: **Unique constraints** (ISBN) and `UniqueConstraintError`.
- :material-magnify: **`is_null()`** for finding missing values.
- :material-code-not-equal: **Predicate composition** with `& | ~`.
- :material-delete-sweep: **`CASCADE`** vs **`RESTRICT`** (vs `SET_NULL` in the
  [task queue](task-queue.md) example).

For a different shape of app — one that **persists across invocations** — see
the [contacts CLI](cli-contacts.md).
