"""Tests for transaction journal recovery (Phase 5 forward-compatibility)."""

from __future__ import annotations

import json
from pathlib import Path

from tinystore import Database
from tinystore.serialization import dumps


def test_recovery_replays_leftover_journal(db_path: Path) -> None:
    # Pre-seed the database with a table file and a journal that proposes
    # a new state. On open, recovery should apply the journaled state.
    Database(db_path)  # initialize directory layout

    # Create an initial table file.
    initial = {"version": 1, "next_id": 1, "rows": []}
    (db_path / "tables").mkdir(parents=True, exist_ok=True)
    (db_path / "tables" / "things.json").write_text(dumps(initial), encoding="utf-8")

    # Write a journal that proposes adding one row.
    journaled = {
        "version": 1,
        "next_id": 2,
        "rows": [{"id": 1, "name": "recovered", "__version": 1}],
    }
    journal_doc = {"txid": "deadbeef", "tables": {"things": journaled}}
    (db_path / "journal" / "deadbeef.json").write_text(dumps(journal_doc), encoding="utf-8")

    # Reopen -> recovery replays.
    Database(db_path)
    state = json.loads((db_path / "tables" / "things.json").read_text(encoding="utf-8"))
    assert state["rows"][0]["name"] == "recovered"
    # Journal removed after recovery.
    assert not (db_path / "journal" / "deadbeef.json").exists()


def test_recovery_noop_when_empty(db_path: Path) -> None:
    Database(db_path)
    db2 = Database(db_path)  # no journals -> clean open
    assert db2.storage.list_journals() == []
