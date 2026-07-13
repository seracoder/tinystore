# Blog app example

A complete TinyStore demo: a simple blog with users, posts, and comments. It
exercises models, CRUD, queries, relationships, joins, transactions, foreign
keys with cascade, and maintenance (`check`/`backup`).

The full source lives at
[`examples/blog_app.py`](https://github.com/seracoder/tinystore/blob/main/examples/blog_app.py).

## Run it

```bash
python examples/blog_app.py
```

## Models

```python
from pathlib import Path

from tinystore import Database, Field, Model, Relationship


db = Database(Path(__file__).parent / "blog_data")


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
```

## Seed data in a transaction

```python
with db.transaction():
    alice = db.insert(User(name="Alice", email="alice@blog.dev"))
    bob = db.insert(User(name="Bob", email="bob@blog.dev"))

    post1 = db.insert(Post(title="Hello World", body="My first post", author_id=alice.id))
    post2 = db.insert(Post(title="TinyStore Tips", body="...", author_id=alice.id))
    db.insert(Post(title="Bob's Review", body="Great!", author_id=bob.id))

    db.insert(Comment(body="Welcome!", post_id=post1.id, author_id=bob.id))
    db.insert(Comment(body="Useful tips.", post_id=post2.id, author_id=bob.id))
```

## Query

```python
for post in (
    db.select(Post)
    .where(Post.author_id == alice.id)
    .order_by(Post.title)
    .all()
):
    print(f"  [{post.id}] {post.title} ({post.views} views)")
```

## Follow a relationship

```python
post = db.get(Post, 1)
author = db.related(post, "author")
print(f"  '{post.title}' by {author.name}")
```

## Join users and posts

```python
rows = (
    db.select(User)
    .join(Post, on=Post.author_id == User.id)
    .order_by(User.name)
    .all()
)
for r in rows:
    print(f"  {r.user.name} wrote '{r.post.title}'")
```

## Update (with optimistic concurrency)

```python
post1 = db.get(Post, 1)
post1.views = 100
db.save(post1)
```

## Cascade delete

Deleting Alice cascades through `on_delete="CASCADE"` to her posts and their
comments:

```python
alice = db.get(User, 1)
db.delete(alice)
print(f"  Users remaining: {db.count(User)}")
print(f"  Posts remaining: {db.count(Post)}")
print(f"  Comments remaining: {db.count(Comment)}")
```

## Maintenance

```python
problems = db.check()
backup_dir = Path(__file__).parent / "blog_backup"
db.backup(backup_dir)
```
