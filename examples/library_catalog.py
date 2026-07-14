"""A TinyStore example: a small library catalog.

Run:  python examples/library_catalog.py

Demonstrates:

- A many-to-one relationship (``Book -> Author``) loaded with ``db.related``.
- A one-to-many traversal (``Author -> books``) via a direct query.
- A three-table join (``Member -- Loan -- Book``) to answer "who borrowed what".
- Unique constraints (ISBN), and how a duplicate is rejected.
- ``is_null()`` to find loans not yet returned.
- Composing predicates with ``& | ~``.
- ``on_delete`` in action: ``CASCADE`` removes a book's loans; the default
  ``RESTRICT`` stops you deleting an author who still has books.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from tinystore import (
    Database,
    Field,
    ForeignKeyError,
    Model,
    Relationship,
    UniqueConstraintError,
)


def main() -> None:
    # Start each run from a clean slate so the demo is deterministic and
    # re-runnable. (A real app would never delete its own database!)
    data_dir = Path(__file__).parent / "library_data"
    if data_dir.exists():
        shutil.rmtree(data_dir)
    db = Database(data_dir)

    # ---- Models -------------------------------------------------------

    class Author(Model):
        id: int | None = Field(default=None, primary_key=True)
        name: str
        country: str = ""

    class Book(Model):
        id: int | None = Field(default=None, primary_key=True)
        title: str
        isbn: str = Field(unique=True)
        year: int = Field(default=0, index=True)
        # on_delete defaults to RESTRICT: an author with books cannot be deleted.
        author_id: int = Field(foreign_key="authors.id")
        author: Author | None = Relationship(foreign_key="author_id")  # type: ignore[assignment]

    class Member(Model):
        id: int | None = Field(default=None, primary_key=True)
        name: str
        email: str = Field(unique=True, index=True)

    class Loan(Model):
        id: int | None = Field(default=None, primary_key=True)
        book_id: int = Field(foreign_key="books.id", on_delete="CASCADE")
        member_id: int = Field(foreign_key="members.id", on_delete="CASCADE")
        borrowed_on: str
        returned_on: str | None = None

    db.register(Author)
    db.register(Book)
    db.register(Member)
    db.register(Loan)

    # ---- Seed data ----------------------------------------------------

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
        db.insert(
            Loan(
                book_id=2,
                member_id=alice.id,
                borrowed_on="2024-02-01",
                returned_on="2024-02-10",
            )
        )
        db.insert(Loan(book_id=3, member_id=2, borrowed_on="2024-03-15"))

    # ---- Unique constraint: a duplicate ISBN is rejected -------------

    print("=== Unique constraint (ISBN) ===")
    try:
        db.insert(Book(title="The Hobbit (dup)", isbn="978-0261102217", year=1937, author_id=1))
    except UniqueConstraintError as exc:
        print(f"  rejected: {exc}")

    # ---- Relationship: many-to-one (book -> author) ------------------

    print("\n=== Relationship: book -> author (many-to-one) ===")
    for book in db.select(Book).order_by(Book.title).all():
        author = db.related(book, "author")
        print(f"  '{book.title}' ({book.year}) by {author.name}")

    # ---- One-to-many (author -> books) via a direct query ------------

    print("\n=== One-to-many: author -> books ===")
    for author in db.select(Author).order_by(Author.name).all():
        books = db.select(Book).where(Book.author_id == author.id).order_by(Book.year).all()
        titles = ", ".join(b.title for b in books) or "—"
        print(f"  {author.name}: {titles}")

    # ---- Three-table join: who borrowed what? ------------------------

    print("\n=== Join: member -- loan -- book ===")
    rows = (
        db.select(Member)
        .join(Loan, on=Loan.member_id == Member.id)
        .join(Book, on=Book.id == Loan.book_id)
        .order_by(Member.name)
        .all()
    )
    for r in rows:
        status = "returned" if r.loan.returned_on else "on loan"
        print(f"  {r.member.name} borrowed '{r.book.title}' ({status})")

    # ---- is_null(): loans not yet returned ---------------------------

    print("\n=== Open loans (returned_on is null) ===")
    open_loans = db.select(Loan).where(Loan.returned_on.is_null()).all()  # type: ignore[union-attr]
    for loan in open_loans:
        print(f"  loan {loan.id}: book_id={loan.book_id} borrowed {loan.borrowed_on}")

    # ---- Composing predicates with & | ~ -----------------------------

    print("\n=== Composed query: Alice's open loans OR anything from 2024-03 ===")
    expr = (
        (Loan.member_id == 1) & Loan.returned_on.is_null()  # type: ignore[union-attr]
    ) | Loan.borrowed_on.startswith("2024-03")
    for loan in db.select(Loan).where(expr).all():
        print(f"  loan {loan.id}: member={loan.member_id} borrowed {loan.borrowed_on}")

    # ---- on_delete="CASCADE": deleting a book removes its loans ------

    print("\n=== on_delete=CASCADE ===")
    print(f"  loans before: {db.count(Loan)}")
    db.delete(Book, 2)  # '1984' has a (returned) loan
    print(f"  loans after deleting book 2: {db.count(Loan)}")

    # ---- on_delete="RESTRICT" (default): author with books is protected

    print("\n=== on_delete=RESTRICT (default) ===")
    try:
        db.delete(Author, 1)  # Tolkien still has 'The Hobbit'
    except ForeignKeyError as exc:
        print(f"  blocked: {exc}")

    # ---- Maintenance -------------------------------------------------

    print("\n=== Maintenance ===")
    problems = db.check()
    print(f"  db.check(): {problems if problems else 'OK'}")

    print("\nDone!")


if __name__ == "__main__":
    main()
