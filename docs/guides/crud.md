# CRUD

Single-row and bulk operations on registered models.

## Single operations

```python
db.insert(instance)               # returns the inserted instance (PK assigned)
db.get(Model, pk)                 # raises DoesNotExist if missing
db.get_by(Model, "email", "x@y")  # single-match lookup (uses index if available)
db.all(Model)
db.save(instance)                 # insert-or-update by primary key
db.update(instance)               # update only (checks optimistic-concurrency version)
db.delete(instance)               # by instance ...
db.delete(Model, pk)              # ... or by primary key
db.count(Model)
```

Every single-op mutation is wrapped as an implicit transaction, so cascading
deletes and other multi-table side effects are all-or-nothing.

## Bulk operations

Each bulk call runs inside one implicit transaction:

```python
db.insert_many([user1, user2, user3])
db.update_many([user1, user2])
db.delete_many(Model, [pk1, pk2, pk3])
```

## Insert

`insert` validates the instance with Pydantic, assigns an auto-increment primary
key (if the model uses one and the PK is `None`), enforces unique constraints and
foreign keys, then writes the table file.

```python
alice = db.insert(User(name="Alice", email="alice@example.com"))
print(alice.id)   # 1
```

Inserting a row whose unique field duplicates an existing one raises
`UniqueConstraintError`. A `foreign_key` pointing at a missing row raises
`ForeignKeyError`.

## Get / get_by

```python
# By primary key. Raises DoesNotExist if missing.
alice = db.get(User, 1)

# Single-match lookup on any column. Uses the hash index if the field is indexed.
alice = db.get_by(User, "email", "alice@example.com")
```

`get_by` raises `DoesNotExist` when no row matches and `MultipleObjectsReturned`
when more than one does.

## Save vs. update

- **`save(instance)`** is insert-or-update by primary key. Use it when you don't
  care whether the row already exists.
- **`update(instance)`** is update only and checks the hidden optimistic-concurrency
  version. If another writer changed the row since you loaded it, it raises
  `StaleDataError`. Disable that check with
  `Database(path, optimistic_concurrency=False)`.

## Delete

```python
db.delete(alice)        # by instance
db.delete(User, 1)      # by primary key
```

Foreign keys declared with `on_delete="CASCADE"` remove dependent rows; with
`on_delete="SET_NULL"` they null out the FK column; the default `"RESTRICT"`
raises `ForeignKeyError` if dependents exist.
