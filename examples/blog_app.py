"""A complete TinyStore example: a simple blog with users, posts, and comments.

Run:  python examples/blog_app.py

Demonstrates: models, CRUD, queries, relationships, joins, transactions,
foreign keys with cascade, and maintenance (check/backup).
"""

from __future__ import annotations

from pathlib import Path

from tinystore import Database, Field, Model, Relationship


def main() -> None:
    db = Database(Path(__file__).parent / "blog_data")

    # ---- Models ----

    class User(Model):
        id: int | None = Field(default=None, primary_key=True)
        name: str
        email: str = Field(unique=True, index=True)

    class Post(Model):
        id: int | None = Field(default=None, primary_key=True)
        title: str
        body: str = ""
        views: int = Field(default=0, index=True)
        author_id: int = Field(foreign_key="users.id", on_delete="CASCADE")
        author: User | None = Relationship(foreign_key="author_id")  # type: ignore[assignment]

    class Comment(Model):
        id: int | None = Field(default=None, primary_key=True)
        body: str
        post_id: int = Field(foreign_key="posts.id", on_delete="CASCADE")
        author_id: int = Field(foreign_key="users.id", on_delete="CASCADE")

    db.register(User)
    db.register(Post)
    db.register(Comment)

    # ---- Seed data (inside a transaction: all-or-nothing) ----

    with db.transaction():
        alice = db.insert(User(name="Alice", email="alice@blog.dev"))
        assert alice.id is not None
        bob = db.insert(User(name="Bob", email="bob@blog.dev"))
        assert bob.id is not None

        post1 = db.insert(Post(title="Hello World", body="My first post", author_id=alice.id))
        post2 = db.insert(Post(title="TinyStore Tips", body="...", author_id=alice.id))
        db.insert(Post(title="Bob's Review", body="Great!", author_id=bob.id))

        assert post1.id is not None
        assert post2.id is not None
        db.insert(Comment(body="Welcome!", post_id=post1.id, author_id=bob.id))
        db.insert(Comment(body="Useful tips.", post_id=post2.id, author_id=bob.id))

    # ---- Queries ----

    print("=== All users ===")
    for user in db.all(User):
        print(f"  {user.id}: {user.name} <{user.email}>")

    print("\n=== Alice's posts (indexed lookup on author_id) ===")
    for post in db.select(Post).where(Post.author_id == alice.id).order_by(Post.title).all():
        print(f"  [{post.id}] {post.title} ({post.views} views)")

    print("\n=== Posts with most views ===")
    for post in db.select(Post).order_by(Post.views, desc=True).limit(2).all():
        print(f"  [{post.id}] {post.title} ({post.views} views)")

    # ---- Relationships ----

    print("\n=== Relationship: post -> author ===")
    post = db.get(Post, 1)
    author = db.related(post, "author")
    print(f"  '{post.title}' by {author.name}")

    # ---- Join: users + their posts ===

    print("\n=== Join: users and posts ===")
    rows = (
        db.select(User)
        .join(Post, on=Post.author_id == User.id)
        .order_by(User.name)
        .all()
    )
    for r in rows:
        print(f"  {r.user.name} wrote '{r.post.title}'")

    # ---- Update with optimistic concurrency ----

    print("\n=== Update ===")
    post1 = db.get(Post, 1)
    post1.views = 100
    db.save(post1)
    print(f"  Post 1 views: {db.get(Post, 1).views}")

    # ---- Cascade delete ===

    print("\n=== Cascade delete: deleting Alice removes her posts + comments ===")
    alice = db.get(User, 1)
    db.delete(alice)
    print(f"  Users remaining: {db.count(User)}")
    print(f"  Posts remaining: {db.count(Post)}")
    print(f"  Comments remaining: {db.count(Comment)}")

    # ---- Maintenance ===

    print("\n=== Maintenance ===")
    problems = db.check()
    print(f"  db.check(): {problems if problems else 'OK'}")
    backup_dir = Path(__file__).parent / "blog_backup"
    db.backup(backup_dir)
    print(f"  db.backup(): {backup_dir}")

    print("\nDone!")


if __name__ == "__main__":
    main()
