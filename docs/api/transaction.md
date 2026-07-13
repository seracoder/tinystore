# Transactions

`db.transaction()` returns a context manager. Writes inside the block are
buffered in memory and committed atomically via a write-ahead journal. An
exception inside the block rolls everything back.

::: tinystore.transaction
