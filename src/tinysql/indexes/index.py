"""In-memory hash indexes rebuilt from table data.

TinySQL stores data as JSON files loaded fully into memory.  An index
accelerates point lookups (``eq``, ``in_``) on indexed fields from O(n) row
scans to O(1) hash-map probes.

Design decisions (Phase 6, correctness-first MVP):

* **Source of truth is the table data, not the index.**  Indexes are rebuilt
  from the current rows list — they are never persisted to disk and never the
  authority.  A rebuild is O(n), no worse than the JSON parse that already
  happened.
* **Rebuild-on-change.**  :meth:`IndexManager.ensure` rebuilds only when the
  rows list identity changes (tracked via ``id()``), avoiding redundant builds
  within a single operation that reads state once.
* **PK index is always built** (primary keys are always indexed).  Unique and
  secondary indexes are built for fields declared ``unique=True`` or
  ``index=True`` in the schema.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..schema import TableSchema

__all__ = ["IndexManager"]


class IndexManager:
    """In-memory hash index over a table's rows.

    Each indexed field maps to ``{value: [row_indices]}``.  Built from a rows
    list via :meth:`build` / :meth:`ensure`; queried via :meth:`lookup`.
    """

    def __init__(self, schema: TableSchema) -> None:
        self._indexed_fields: set[str] = set()
        for f in schema.fields:
            if f.primary_key or f.unique or f.index:
                self._indexed_fields.add(f.name)
        self._maps: dict[str, dict[Any, list[int]]] = {}
        self._rows_id: int | None = None

    @property
    def indexed_fields(self) -> frozenset[str]:
        return frozenset(self._indexed_fields)

    def has_index(self, field: str) -> bool:
        """Return ``True`` if *field* has an index."""
        return field in self._indexed_fields

    def build(self, rows: list[dict[str, Any]]) -> None:
        """Build all index maps from *rows*."""
        self._maps = {}
        for field in self._indexed_fields:
            field_map: dict[Any, list[int]] = {}
            for i, row in enumerate(rows):
                field_map.setdefault(row.get(field), []).append(i)
            self._maps[field] = field_map
        self._rows_id = id(rows)

    def ensure(self, rows: list[dict[str, Any]]) -> None:
        """Rebuild the index from *rows*.

        Always rebuilds for correctness.  The source of truth is the table data,
        and since all rows are already in memory (parsed from JSON), the O(n)
        build cost is negligible compared to the I/O already paid.
        """
        self.build(rows)

    def lookup(self, field: str, value: Any) -> list[int] | None:
        """Return row indices where ``field == value``.

        Returns ``None`` if *field* is not indexed (caller should scan).
        Returns an empty list if indexed but no match.
        """
        field_map = self._maps.get(field)
        if field_map is None:
            return None
        return field_map.get(value, [])

    def lookup_many(self, field: str, values: list[Any]) -> list[int] | None:
        """Return row indices where ``field`` is in *values*.

        Returns ``None`` if *field* is not indexed.  Duplicates in the result
        are not removed — callers should deduplicate if needed.
        """
        field_map = self._maps.get(field)
        if field_map is None:
            return None
        result: list[int] = []
        for v in values:
            indices = field_map.get(v)
            if indices:
                result.extend(indices)
        return result
