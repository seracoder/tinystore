# Indexes

In-memory hash indexes accelerate `eq` (`==`) and `in_` lookups on fields
declared with `index=True`, `unique=True`, or `primary_key=True`. Indexes are
rebuilt from table data on each access — the source of truth is always the data.

::: tinystore.indexes.index
