# Models & fields

A model subclasses [`Model`](../api/model.md) (which itself subclasses
`pydantic.BaseModel`) and declares fields with [`Field`](../api/model.md):

```python
class Post(Model):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    slug: str = Field(unique=True)
    views: int = Field(default=0, index=True)
    author_id: int = Field(foreign_key="users.id", on_delete="CASCADE")

    class Meta:
        table_name = "posts"   # optional; defaults to a pluralized snake_case name
```

`Field` wraps `pydantic.Field` and attaches TinyStore metadata:

| Keyword         | Default        | Description                                                            |
| --------------- | -------------- | --------------------------------------------------------------------- |
| `primary_key`   | `False`        | Marks the primary key. One per model. Enables auto-increment by default. |
| `autoincrement` | `=primary_key` | Explicitly enable/disable auto-increment for the PK.                 |
| `unique`        | `False`        | Enforces a uniqueness constraint across the table.                    |
| `index`         | `False`        | Builds an in-memory hash index for O(1) eq/in lookups.               |
| `nullable`      | inferred       | Allows `NULL`; fields with a default are nullable.                    |
| `foreign_key`   | `None`         | `"table.column"` reference, validated on write.                       |
| `on_delete`     | `"RESTRICT"`   | `"RESTRICT"`, `"CASCADE"`, or `"SET_NULL"`.                           |

Any other keyword arguments (`ge=`, `min_length=`, `description=`, ...) are
forwarded straight to Pydantic, so all of Pydantic's validation works.

```python
class Product(Model):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(min_length=1, max_length=100)
    price: float = Field(ge=0, description="Price in USD")
    sku: str = Field(unique=True, pattern=r"^[A-Z]{3}-\d+$")
```

## Table naming

By default the table name is derived from the class: `User -> users`,
`Address -> addresses`, `Person -> people`. Override it with a nested `Meta`:

```python
class User(Model):
    ...
    class Meta:
        table_name = "accounts"
```

## Field access for queries

Class-level field access — e.g. `User.age` — resolves to a `FieldProxy` usable
both by static type checkers and at runtime for query building:

```python
db.select(User).where(User.age < 35)
```

This is how the typed query DSL works. See the [Querying guide](querying.md).

## Schema evolution

When you reopen a database, TinyStore compares the registered model's schema
against the stored fingerprint.

- **Additive** changes (new nullable/defaulted field) are accepted automatically.
- **Breaking** changes (removed field, type change) raise `SchemaError`.

Use `db.reset_schema()` to discard stored metadata (destructive — it does **not**
delete data files, but future reads may fail if the data no longer matches).

## Relationships

Relationships are declared separately with `Relationship(...)`. See the
[Relationships guide](relationships.md).
