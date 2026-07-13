# Locking

A database-wide write lock with two layers: an in-process `threading.RLock` and
a cross-process `portalocker` `RLock` on `tinystore.lock`.

::: tinystore.locking
