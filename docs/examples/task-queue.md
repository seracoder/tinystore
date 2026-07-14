# Task queue example

A small background **job queue** built on TinyStore. Workers enqueue jobs,
claim the highest-priority queued job, run it, and mark it done. It's a compact
way to see the features that matter for stateful apps: **transactions**,
**indexed lookups**, a **state machine**, and **optimistic concurrency** under
contention.

The full source lives at
[`examples/task_queue.py`](https://github.com/seracoder/tinystore/blob/main/examples/task_queue.py).

---

## Run it

```bash
python examples/task_queue.py
```

The script starts from a clean slate each run (it removes its own `queue_data/`
directory first), so the output is deterministic.

---

## Define the models

A `Worker` runs jobs; a `Job` belongs to at most one worker.

```python
from tinystore import Database, Field, Model, StaleDataError

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"


class Worker(Model):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    status: str = Field(default="idle", index=True)


class Job(Model):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    status: str = Field(default=QUEUED, index=True)   # (1)
    priority: int = Field(default=0, index=True)      # (1)
    payload: str = ""
    attempts: int = 0
    worker_id: int | None = Field(                    # (2)
        default=None, foreign_key="workers.id", on_delete="SET_NULL"
    )
```

1. **`index=True`** on `status` and `priority` turns the dequeue query
   ("highest-priority queued job") into an index-narrowed lookup instead of a
   full scan.
2. **`on_delete="SET_NULL"`** means removing a worker *detaches* its jobs (sets
   `worker_id = None`) rather than deleting them. `worker_id` is nullable to
   allow this.

!!! note "Why plain strings for status?"
    TinyStore persists rows with Pydantic's `model_dump(mode="json")`, so
    `enum.Enum`, `datetime`, and `UUID` all round-trip fine. This example uses
    plain strings to keep the on-disk JSON readable and the query examples
    obvious. See [Models & fields](../guides/models.md).

---

## Seed workers and jobs in one transaction

Bulk inserts run inside a single implicit transaction, but grouping the
*whole* seed in an explicit `db.transaction()` makes it all-or-nothing: if any
row fails validation, none of it lands.

```python
with db.transaction():
    w1 = db.insert(Worker(name="worker-1"))
    w2 = db.insert(Worker(name="worker-2"))

    db.insert_many(
        [
            Job(name="resize-image", priority=5, payload="img/001.png"),
            Job(name="send-welcome-email", priority=9, payload="user=42"),
            Job(name="generate-report", priority=2, payload="Q3"),
            Job(name="cleanup-temp", priority=1, payload="/tmp"),
        ]
    )
```

---

## Claim the next job atomically

The heart of the queue: pick the highest-priority queued job and mark it
`running` **in the same transaction**, so two workers can never grab the same
job.

```python
def claim(worker: Worker) -> Job | None:
    with db.transaction():
        job = (
            db.select(Job)
            .where(Job.status == QUEUED)
            .order_by(Job.priority, desc=True)
            .first()
        )
        if job is None:
            return None
        job.status = RUNNING
        job.attempts += 1
        job.worker_id = worker.id
        return db.save(job)
```

!!! tip "Why the explicit transaction?"
    Without it, `select(...).first()` and `db.save(job)` would each take and
    release the write lock separately — two workers could read the same job
    between those steps. Wrapping both in `db.transaction()` holds the
    database-wide lock for the whole critical section. See
    [Transactions](../guides/transactions.md).

---

## Optimistic concurrency under contention

What happens when two workers somehow hold the **same stale snapshot** of a
job? TinyStore tags every row with a hidden version. `db.update()` checks that
the stored version still matches the one you loaded — if another writer got
there first, it raises `StaleDataError`.

```python
held_by_a = db.get(Job, 2)   # version N
held_by_b = db.get(Job, 2)   # version N (same snapshot)

held_by_a.status = DONE
db.update(held_by_a)         # winner: stored version bumps to N+1

held_by_b.status = FAILED
try:
    db.update(held_by_b)     # loser: stale snapshot
except StaleDataError:
    fresh = db.get(Job, 2)   # reload the current row, then reconcile
```

!!! check "The recovery pattern"
    `StaleDataError` is not fatal — **reload the row and decide what to do**.
    Because the write-ahead journal already committed worker-A's update, a
    crashed worker-B can safely re-read on restart and skip work that's done.

!!! warning "save vs update"
    `db.save(instance)` is insert-or-update and delegates to `update` for
    existing rows, so it **also** checks the version. Use `db.update(instance)`
    when you specifically mean "update an existing row" and want the check.

---

## Removing a worker detaches its jobs

Because `Job.worker_id` uses `on_delete="SET_NULL"`, deleting a worker nulls
out the foreign key on its jobs — the jobs survive, unassigned:

```python
db.delete(w2)                       # worker-2 owned job 1
print(db.get(Job, 1).worker_id)     # -> None
```

Contrast this with `on_delete="CASCADE"` (used in the
[library example](library-catalog.md)), which would delete the dependent rows
entirely. The third option, `"RESTRICT"` (the default), refuses the delete and
raises `ForeignKeyError` while dependents exist.

---

## Maintenance

```python
problems = db.check()   # -> [] when the database is consistent
```

`db.check()` validates that every table file parses, primary keys are unique,
`next_id` exceeds the largest id in use, and registered foreign keys resolve.
See [Storage format](../guides/storage.md).

---

## Recap

This example demonstrated:

- :material-database-plus: **Bulk insert** (`insert_many`) inside a transaction.
- :material-database-search: **Indexed queries** (`status`, `priority`) for fast dequeue.
- :material-sync: **Atomic state transitions** inside `db.transaction()`.
- :material-shield-account: **Optistic concurrency** and `StaleDataError` recovery.
- :material-link-off: **`on_delete="SET_NULL"`** to detach instead of delete.
- :material-wrench: **Maintenance** via `db.check()`.

Next, see the [library catalog example](library-catalog.md) for relationships,
joins, and `on_delete` variations, or the [contacts CLI](cli-contacts.md) for
an app that persists across invocations.
