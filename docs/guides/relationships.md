# Relationships

Relationships are declared with [`Relationship(...)`](../api/relationships.md) as
a field default and loaded explicitly via `db.related()`. Relationship fields are
**never persisted** — only the foreign-key column is stored.

```python
from tinystore import Relationship

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

## Cardinality

The cardinality is inferred from which side holds the FK:

- **many-to-one** (local FK): `db.related(post, "author")` -> single instance or `None`.
- **one-to-many** (remote FK): `db.related(user, "posts")` -> list of instances.

The side is determined automatically from the declared `foreign_key`; if multiple
models reference the same table ambiguously, `RelationshipError` is raised.

## A full example

```python
class User(Model):
    id: int | None = Field(default=None, primary_key=True)
    name: str

class Post(Model):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    author_id: int = Field(foreign_key="users.id", on_delete="CASCADE")
    author: User | None = Relationship(foreign_key="author_id")
```

Declare the relationship on whichever side you want to traverse from. To go from
a user to their posts without declaring a reverse relationship, use a join (see
the [Joins guide](joins.md)) or query directly:

```python
user_posts = db.select(Post).where(Post.author_id == user.id).all()
```

## Relationships vs. joins

- Use a **`Relationship`** when you have a clear "parent" object and want to
  follow one FK to its target (or to its dependents).
- Use a **join** when you want to combine rows from multiple tables into a single
  result set.
