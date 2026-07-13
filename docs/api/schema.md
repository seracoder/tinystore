# Schema

The table schema: declared fields, their metadata, primary key, unique
constraints, indexes, and foreign keys. TinyStore stores a schema fingerprint per
table in `metadata.json` and compares it on open to detect breaking changes.

::: tinystore.schema
