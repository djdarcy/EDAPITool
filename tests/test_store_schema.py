"""
Schema versions and the migration chain (#22 criterion 15: a store one
version old is migrated on open; two versions old is migrated step by
step, or refused with a named path -- never silently misread).
"""

import pytest

from APITool import store
from APITool.store import registry, schema


def _at_version_1(path):
    """A store shaped as version 1 wrote it: no journal-derived tables."""
    conn = store.open_store(path)
    try:
        with conn:
            for table in reversed(registry.derived()):
                if table.name not in ("market_snapshot", "market_item"):
                    conn.execute(f"DROP TABLE {table.name}")
            conn.execute("PRAGMA user_version = 1")
    finally:
        conn.close()


def test_a_fresh_store_is_at_this_code_s_version_with_every_registered_table(tmp_path):
    conn = store.open_store(tmp_path / "store.db")
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == schema.SCHEMA_VERSION == 2
        present = {name for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")}
        assert present == set(registry.names())
    finally:
        conn.close()


def test_a_store_one_version_old_is_migrated_on_open(tmp_path):
    path = tmp_path / "store.db"
    _at_version_1(path)
    conn = store.open_store(path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        assert store.verify(conn) == []
    finally:
        conn.close()


def test_a_store_two_versions_old_is_migrated_through_each_step(tmp_path, monkeypatch):
    path = tmp_path / "store.db"
    _at_version_1(path)
    ran = []
    monkeypatch.setattr(store, "SCHEMA_VERSION", 3)
    monkeypatch.setattr(schema, "SCHEMA_VERSION", 3)
    monkeypatch.setitem(schema.MIGRATIONS, 3, lambda conn: ran.append(3))
    conn = store.open_store(path)
    try:
        assert ran == [3], "step 2 is the real one; step 3 the planted one, run after it"
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        assert "construction_delta" in {name for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        conn.close()


def test_a_store_whose_migration_step_is_missing_is_refused_with_its_path(tmp_path, monkeypatch):
    path = tmp_path / "store.db"
    _at_version_1(path)
    monkeypatch.delitem(schema.MIGRATIONS, 2)
    with pytest.raises(store.StoreVersionError) as caught:
        store.open_store(path)
    message = str(caught.value)
    assert "no migration step to 2" in message and str(path) in message
    import sqlite3
    raw = sqlite3.connect(path)
    try:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 1, "refused, not half-migrated"
    finally:
        raw.close()
