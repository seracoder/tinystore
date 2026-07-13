# Joins

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

## Chaining joins

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

## How it works (and limits)

Joins are evaluated in memory with nested loops — every participating table is
read fully. This is deliberate: TinyStore stores rows as JSON files, so a
disk-efficient join is outside the scope of v1.

That means joins are great for thousands of rows but not for joining tables of
millions. If you need heavy analytical joins, export to SQLite or a real OLAP
engine (see the [roadmap](../index.md#where-next)).

## `kind`

The `kind` argument to `.join(...)` accepts:

| `kind`   | Behavior                                                          |
| -------- | ---------------------------------------------------------------- |
| `"inner"`| (default) Rows with no match on the right are dropped.          |
| `"left"` | All left rows are kept; unmatched right columns are `None`.     |
