# API reference

Auto-generated from the TinyStore source. Every public class, method, and
exception is documented here directly from its docstring.

The top-level package re-exports the public API:

::: tinystore

## Modules

| Module | Purpose |
| --- | --- |
| [`database`](database.md) | `Database` — the main entry point. |
| [`model`](model.md) | `Model` and `Field` — defining tables. |
| [`relationships`](relationships.md) | `Relationship` and `db.related()`. |
| [`schema`](schema.md) | `TableSchema`, field metadata, schema evolution. |
| [`table`](table.md) | `Table` — the in-memory collection backing a model. |
| [`query`](query.md) | `SelectQuery`, joins, expressions. |
| [`transaction`](transaction.md) | `Transaction` context manager. |
| [`storage`](storage.md) | Storage backends (`JsonStorage`). |
| [`indexes`](indexes.md) | In-memory hash indexes. |
| [`locking`](locking.md) | File / thread locking. |
| [`serialization`](serialization.md) | Row serialization internals. |
| [`exceptions`](exceptions.md) | The `TinyStoreError` hierarchy. |
