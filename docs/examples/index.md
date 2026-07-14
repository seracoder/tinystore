# Examples

Complete, runnable apps. Each one focuses on a different shape of problem and a
different set of TinyStore features — read it top to bottom or copy it as a
starting point.

- [:material-post: **Blog app**](blog-app.md) — users, posts, and comments.
  The grand tour: models, CRUD, queries, relationships, joins, transactions,
  foreign keys with cascade, and maintenance.
- [:material-sync: **Task queue**](task-queue.md) — a background job queue.
  Transactions, indexed dequeue, a state machine, and **optimistic concurrency**
  under contention.
- [:material-bookshelf: **Library catalog**](library-catalog.md) — authors,
  books, members, loans. **Relationships**, **three-table joins**, unique
  constraints, `is_null()`, predicate composition, and every `on_delete`
  behavior.
- [:material-console: **Contacts CLI**](cli-contacts.md) — a persistent
  terminal contacts manager. The **embedded CLI tool** use case: data survives
  between runs, indexed lookups, text search, and `list[str]` tags.

Every example lists how to **run it** at the top of its page.

Looking for a single feature instead of a whole app? Try the
**[Guides](../guides/index.md)**.
