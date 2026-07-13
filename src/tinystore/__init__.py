"""TinyStore — a lightweight, Pydantic-native relational database.

Persists data as human-readable JSON files. No external server.

Example
-------

.. code-block:: python

    from tinystore import Database, Model, Field

    db = Database("./app_data")


    class User(Model):
        id: int | None = Field(default=None, primary_key=True)
        name: str
        email: str = Field(unique=True, index=True)


    db.register(User)
    user = db.insert(User(name="Alice", email="alice@example.com"))
    print(db.select(User).where(User.name == "Alice").first())  # Phase 2+
"""

from .database import Database
from .exceptions import (
    DoesNotExist,
    ForeignKeyError,
    IntegrityError,
    LockTimeoutError,
    MultipleObjectsReturned,
    QueryError,
    RelationshipError,
    SchemaError,
    StaleDataError,
    StorageError,
    TinyStoreError,
    TransactionError,
    UniqueConstraintError,
)
from .fields import Field
from .model import Model
from .relationships import Relationship
from .schema import TableSchema
from .table import Table

__version__ = "0.1.0"

__all__ = [
    "Database",
    "DoesNotExist",
    "Field",
    "ForeignKeyError",
    "IntegrityError",
    "LockTimeoutError",
    "Model",
    "MultipleObjectsReturned",
    "QueryError",
    "Relationship",
    "RelationshipError",
    "SchemaError",
    "StaleDataError",
    "StorageError",
    "Table",
    "TableSchema",
    "TinyStoreError",
    "TransactionError",
    "UniqueConstraintError",
    "__version__",
]
