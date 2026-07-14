"""A TinyStore example: a small background job queue.

Run:  python examples/task_queue.py

Demonstrates:

- Bulk inserts inside a single transaction.
- Indexed dequeue queries (``status`` and ``priority``).
- A queued / running / done state machine.
- Atomic state transitions inside ``db.transaction()``.
- Optimistic concurrency: two workers race on the same job, one wins and the
  other gets a ``StaleDataError`` — and the example shows how to recover.
- ``on_delete="SET_NULL"``: removing a worker detaches (not deletes) its jobs.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from tinystore import Database, Field, Model, StaleDataError

# Plain-string status constants. Strings keep queries and the JSON on disk
# simple and readable (see docs/guides/models.md for richer Pydantic types).
QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"


def main() -> None:
    # Start each run from a clean slate so the demo is deterministic and
    # re-runnable. (A real app would never delete its own database!)
    data_dir = Path(__file__).parent / "queue_data"
    if data_dir.exists():
        shutil.rmtree(data_dir)
    db = Database(data_dir)

    # ---- Models -------------------------------------------------------

    class Worker(Model):
        id: int | None = Field(default=None, primary_key=True)
        name: str
        status: str = Field(default="idle", index=True)

    class Job(Model):
        id: int | None = Field(default=None, primary_key=True)
        name: str
        status: str = Field(default=QUEUED, index=True)
        priority: int = Field(default=0, index=True)
        payload: str = ""
        attempts: int = 0
        # A job optionally belongs to a worker. Deleting the worker detaches
        # the job instead of deleting it.
        worker_id: int | None = Field(default=None, foreign_key="workers.id", on_delete="SET_NULL")

    db.register(Worker)
    db.register(Job)

    # ---- Seed workers + a batch of jobs (one atomic transaction) ------

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

    print("=== Enqueued (bulk insert in one transaction) ===")
    for job in db.select(Job).order_by(Job.priority, desc=True).all():
        print(f"  [{job.id}] {job.status:7} pri={job.priority} {job.name}")

    # ---- Dequeue: highest-priority queued job (uses indexes) ---------

    def claim(worker: Worker) -> Job | None:
        """Atomically pick the next queued job and mark it running.

        The whole pick-and-update runs in one transaction, so two workers
        can never grab the same job.
        """
        with db.transaction():
            job = (
                db.select(Job).where(Job.status == QUEUED).order_by(Job.priority, desc=True).first()
            )
            if job is None:
                return None
            job.status = RUNNING
            job.attempts += 1
            job.worker_id = worker.id
            return db.save(job)

    print("\n=== Workers claim jobs ===")
    for w in (w1, w2):
        claimed = claim(w)
        if claimed is not None:
            print(f"  {w.name} claimed [{claimed.id}] {claimed.name} (attempts={claimed.attempts})")

    # ---- Optimistic concurrency: two workers, same job, one wins ----

    print("\n=== Optimistic concurrency race ===")
    # Two workers each load the SAME job snapshot (version N).
    held_by_a = db.get(Job, 2)
    held_by_b = db.get(Job, 2)

    held_by_a.status = DONE
    db.update(held_by_a)  # winner: stored version bumps to N+1
    print(f"  worker-A finished job {held_by_a.id} (version bumped)")

    held_by_b.status = FAILED
    try:
        db.update(held_by_b)  # loser: stale snapshot
    except StaleDataError:
        print(f"  worker-B rejected: StaleDataError (job {held_by_b.id} changed)")
        # Recover by reloading the current row and reconciling.
        fresh = db.get(Job, 2)
        print(f"  reloaded job {fresh.id}: status={fresh.status} -> nothing to do")

    # ---- on_delete="SET_NULL": removing a worker frees its jobs ------

    print("\n=== on_delete=SET_NULL ===")
    print(f"  job 1 worker_id before: {db.get(Job, 1).worker_id}")
    db.delete(w2)  # worker-2 owned job 1
    print(f"  job 1 worker_id after deleting worker-2: {db.get(Job, 1).worker_id}")

    # ---- Maintenance -------------------------------------------------

    print("\n=== Maintenance ===")
    problems = db.check()
    print(f"  db.check(): {problems if problems else 'OK'}")

    print("\nDone!")


if __name__ == "__main__":
    main()
