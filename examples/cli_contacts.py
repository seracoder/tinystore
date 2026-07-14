"""A TinyStore example: a persistent contacts CLI.

The database lives in a directory next to this script and persists across
invocations, so this is the classic "embedded database for a CLI tool" use
case. Each run reopens the same directory; TinyStore checks the stored schema
fingerprint on open and accepts additive changes automatically.

Try a full session:

    python examples/cli_contacts.py add --name "Alice" --email alice@x.dev --tag team
    python examples/cli_contacts.py add --name "Bob" --email bob@x.dev --phone 555-1234
    python examples/cli_contacts.py list
    python examples/cli_contacts.py search ali
    python examples/cli_contacts.py show 1
    python examples/cli_contacts.py tag 1 --add vip
    python examples/cli_contacts.py list --tag vip
    python examples/cli_contacts.py delete 2
    python examples/cli_contacts.py stats

Demonstrates: a database that persists between runs, indexed single-row lookup
(``get_by`` on email), text search with ``contains()``, unique-constraint
handling, a ``list[str]`` field (tags), and filtered listing/counting.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from tinystore import Database, DoesNotExist, Field, Model, UniqueConstraintError

DB_PATH = Path(__file__).parent / "contacts_data"


class Contact(Model):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(unique=True, index=True)
    phone: str | None = None
    notes: str = ""
    tags: list[str] = Field(default_factory=list)


def get_db() -> Database:
    """Open (or create) the database and register the model.

    Calling this on every invocation is cheap: it reopens the directory and
    re-checks the schema fingerprint against the stored one.
    """
    db = Database(DB_PATH)
    db.register(Contact)
    return db


# ---- commands -----------------------------------------------------------


def cmd_add(args: argparse.Namespace) -> int:
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


def cmd_list(args: argparse.Namespace) -> int:
    db = get_db()
    contacts = db.select(Contact).order_by(Contact.name).all()
    if args.tag:
        contacts = [c for c in contacts if args.tag in c.tags]
    if not contacts:
        print("(no contacts)")
        return 0
    for c in contacts:
        tags = f"  [{', '.join(c.tags)}]" if c.tags else ""
        print(f"  [{c.id}] {c.name} <{c.email}>{tags}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    db = get_db()
    q = args.query
    matches = (
        db.select(Contact)
        .where(Contact.name.contains(q) | Contact.email.contains(q))  # type: ignore[attr-defined]
        .order_by(Contact.name)
        .all()
    )
    if not matches:
        print("(no matches)")
        return 0
    for c in matches:
        print(f"  [{c.id}] {c.name} <{c.email}>")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    db = get_db()
    try:
        c = db.get(Contact, args.id)
    except DoesNotExist:
        print(f"error: no contact with id {args.id}", file=sys.stderr)
        return 1
    print(f"id:     {c.id}")
    print(f"name:   {c.name}")
    print(f"email:  {c.email}")
    print(f"phone:  {c.phone or '(none)'}")
    print(f"notes:  {c.notes or '(none)'}")
    print(f"tags:   {', '.join(c.tags) if c.tags else '(none)'}")
    return 0


def cmd_tag(args: argparse.Namespace) -> int:
    db = get_db()
    try:
        c = db.get(Contact, args.id)
    except DoesNotExist:
        print(f"error: no contact with id {args.id}", file=sys.stderr)
        return 1
    current = set(c.tags)
    if args.add:
        current.update(args.add)
    if args.remove:
        current.difference_update(args.remove)
    c.tags = sorted(current)
    db.save(c)
    print(f"updated [{c.id}] tags: {', '.join(c.tags) if c.tags else '(none)'}")
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    db = get_db()
    try:
        db.delete(Contact, args.id)
    except DoesNotExist:
        print(f"error: no contact with id {args.id}", file=sys.stderr)
        return 1
    print(f"deleted contact {args.id}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    db = get_db()
    contacts = db.all(Contact)
    tag_counts = Counter(t for c in contacts for t in c.tags)
    print(f"contacts: {len(contacts)}")
    print(f"with phone: {sum(1 for c in contacts if c.phone)}")
    if tag_counts:
        print("tags:")
        for tag, count in tag_counts.most_common():
            print(f"  {tag}: {count}")
    return 0


# ---- argument parsing ---------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cli_contacts", description="A TinyStore contacts CLI.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("add", help="Add a contact.")
    p.add_argument("--name", required=True)
    p.add_argument("--email", required=True)
    p.add_argument("--phone", default=None)
    p.add_argument("--notes", default="")
    p.add_argument("--tag", action="append", help="Repeatable tag.")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("list", help="List contacts (optionally filtered by --tag).")
    p.add_argument("--tag", default=None)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("search", help="Search name and email by substring.")
    p.add_argument("query")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("show", help="Show one contact by id.")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("tag", help="Add or remove tags on a contact.")
    p.add_argument("id", type=int)
    p.add_argument("--add", action="append", help="Tag to add (repeatable).")
    p.add_argument("--remove", action="append", help="Tag to remove (repeatable).")
    p.set_defaults(func=cmd_tag)

    p = sub.add_parser("delete", help="Delete a contact by id.")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_delete)

    p = sub.add_parser("stats", help="Show summary counts.")
    p.set_defaults(func=cmd_stats)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)  # type: ignore[no-any-return]


if __name__ == "__main__":
    sys.exit(main())
