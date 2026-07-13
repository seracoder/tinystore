# Transactions

Group writes so they either **all land** or **all roll back**. Transactions
acquire the database-wide write lock for their full duration and buffer all
changes in memory.

```python
with db.transaction():
    db.insert(User(name="Carol", email="carol@example.com"))
    db.insert(User(name="Dave", email="dave@example.com"))
# An exception inside the block discards the buffer; no table files are touched.
```

## Write-ahead journal

On commit, the transaction writes a `journal/<txid>.json` file containing the
full new state of every touched table and fsyncs it. That durable write is the
**commit point** — after it succeeds, the transaction is committed even if the
process crashes before all table files are updated. On the next open, recovery
replays any leftover journals idempotently and removes them.

Every single-op mutation (insert, update, delete) runs inside an implicit
transaction via the same code path, so cascading deletes and multi-table side
effects are atomic too.

!!! warning "Nested transactions are not supported"
    Beginning a transaction while one is already active on the same thread raises
    `TransactionError`.

## Optimistic concurrency

Each row carries a hidden version number. When you load a row, mutate it, and
call `db.save()` / `db.update()`, TinyStore checks that the stored version still
matches the one you loaded — if another writer got there first, it raises
`StaleDataError`.

```python
alice = db.get(User, 1)
alice.age = 31
db.update(alice)   # checks __version == stored version
```

Disable optimistic concurrency entirely with
`Database(path, optimistic_concurrency=False)`.

## The lock for the duration

A transaction holds the database-wide write lock (see the
[Locking model](locking.md)) until it commits or rolls back. That means:

- No other thread or process can write concurrently — good for correctness.
- A long-running transaction blocks all other operations — keep them short.
