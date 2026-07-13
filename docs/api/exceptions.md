# Exceptions

All errors inherit from `TinyStoreError`:

```
TinyStoreError
├── IntegrityError
│   ├── UniqueConstraintError
│   ├── ForeignKeyError
│   └── StaleDataError          # optimistic-concurrency conflict
├── DoesNotExist
├── MultipleObjectsReturned
├── LockTimeoutError
├── TransactionError
├── SchemaError
├── RelationshipError
├── QueryError                  # incompatible-type comparisons, bad expressions
└── StorageError
```

Catch the specific ones you care about:

```python
from tinystore import DoesNotExist, UniqueConstraintError

try:
    db.get(User, 999)
except DoesNotExist:
    ...
```

::: tinystore.exceptions
