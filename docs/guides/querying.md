# Querying

Build queries with `db.select(Model)`. Field comparisons are made against the
model class (e.g. `User.age`), which returns a field proxy that builds an
expression — no magic strings, no `eval`.

```python
young = (
    db.select(User)
    .where(User.age < 35)
    .order_by(User.name)
    .limit(10)
    .all()
)
```

## Operators

| Comparison                | Methods                                                            |
| ------------------------- | ----------------------------------------------------------------- |
| `==`, `!=`, `<`, `<=`, `>`, `>=` | —                                                          |
| membership                | `User.role.in_([...])`, `User.role.not_in([...])`                 |
| strings                   | `.contains(...)`, `.startswith(...)`, `.endswith(...)`            |
| null checks               | `.is_null()`, `.is_not_null()`                                    |
| combine                   | `&` (and), `\|` (or), `~` (not)                                   |

```python
# Compose predicates with & | ~, or pass several to .where(...) (AND-combined).
admins = (
    db.select(User)
    .where(
        (User.age >= 18)
        & User.email.contains("@example.com")
        & User.role.in_(["admin", "editor"])
    )
    .order_by(User.age, desc=True)
    .all()
)
```

## Terminal methods

| Method          | Returns           | Raises                                            |
| --------------- | ----------------- | ------------------------------------------------- |
| `.all()`        | `list[Model]`     |                                                   |
| `.first()`      | `Model \| None`   |                                                   |
| `.one()`        | `Model`           | `DoesNotExist`, `MultipleObjectsReturned`         |
| `.one_or_none()`| `Model \| None`   | `MultipleObjectsReturned`                         |
| `.count()`      | `int`             |                                                   |
| `.exists()`     | `bool`            |                                                   |

`.order_by(field)` is repeatable for multi-key sort; `.limit(n)` and
`.offset(n)` paginate.

```python
page = (
    db.select(User)
    .where(User.active == True)
    .order_by(User.name)
    .limit(20)
    .offset(40)
    .all()
)
```

## Indexes

Fields declared with `index=True`, `unique=True`, or `primary_key=True` get an
in-memory hash index. Queries with `eq` (`==`) or `in_` conditions on indexed
fields are automatically narrowed via the index instead of scanning all rows.
Indexes are rebuilt from table data on each access — the source of truth is
always the data, never the index.

## Query semantics

- `None` and missing fields are treated as "absent": ordering comparisons
  against `None` return `False`; use `is_null()` / `is_not_null()` explicitly.
- Comparing two non-null values of **incompatible types** (e.g. an `int` field
  against a `str` literal) raises `QueryError` rather than failing silently.
- Results are sorted by `(type_rank, value)`, so mixed types never raise during
  ordering and the output is always deterministic.

## Joins

Combine two or more registered models with `.join(...)`. See the
[Joins guide](joins.md).
