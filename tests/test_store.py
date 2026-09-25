"""
The observation store: one file, three verbs, and the rule that a rebuild
never touches what cannot be got back.

Everything here runs under the conftest's ``ED_CONFIG_DIR``, so ``store.db``
lands in a scratch directory and no test ever opens ``~/edapitool/store.db``.
The tests that need a path of their own pass one; the tests that prove the
redirection do not.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from APITool import settings, store
from APITool.cli import main
from APITool.store import registry, schema
from APITool.store.market import canonical_name, rows_from_market_json

MARKET_JSON = {
    "timestamp": "2026-09-08T03:13:00Z",
    "event": "Market",
    "MarketID": 3226578176,
    "StationName": "Ryman Enterprise",
    "StationType": "Coriolis",
    "StarSystem": "Lhou Mans",
    "Items": [
        {"id": 128049153, "Name": "$palladium_name;", "Name_Localised": "Palladium",
         "Category": "$MARKET_category_metals;", "Category_Localised": "Metals",
         "BuyPrice": 13, "SellPrice": 12, "MeanPrice": 13, "StockBracket": 3,
         "DemandBracket": 0, "Stock": 999, "Demand": 0,
         "Consumer": False, "Producer": True, "Rare": False},
        {"id": 128049154, "Name": "$gold_name;", "Name_Localised": "Gold",
         "Category": "$MARKET_category_metals;", "Category_Localised": "Metals",
         "BuyPrice": 0, "SellPrice": 9401, "MeanPrice": 9401, "StockBracket": 0,
         "DemandBracket": 2, "Stock": 0, "Demand": 42,
         "Consumer": True, "Producer": False, "Rare": False},
    ],
}


def market_bytes(**overrides) -> bytes:
    payload = {**MARKET_JSON, **overrides}
    return json.dumps(payload).encode("utf-8")


def plant_market(conn, payload: bytes = None, *, source_id: int = None) -> int:
    """A raw market observation, inserted the way a reader would (via archive)."""
    payload = payload or market_bytes()
    obs_id = store.archive("market_json", payload, locator="C:/journal/Market.json",
                           subject="3226578176", observed_at="2026-09-08T03:13:00Z",
                           commander="Extreme", commander_fid="F1234", machine="plzwork",
                           conn=conn)
    assert obs_id is not None
    return obs_id


def table_dump(conn, name: str) -> list[tuple]:
    return conn.execute(f"SELECT * FROM {name} ORDER BY 1").fetchall()


# --------------------------------------------------------------------------
# open_store
# --------------------------------------------------------------------------

def test_a_fresh_store_is_created_at_the_current_version(tmp_path):
    path = tmp_path / "store.db"
    conn = store.open_store(path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == schema.SCHEMA_VERSION
        present = {n for (n,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        assert present == set(registry.names())
    finally:
        conn.close()


def test_opening_twice_is_idempotent(tmp_path):
    path = tmp_path / "store.db"
    first = store.open_store(path)
    tables_before = table_dump(first, "sqlite_master")
    first.close()
    second = store.open_store(path)
    try:
        assert second.execute("PRAGMA user_version").fetchone()[0] == schema.SCHEMA_VERSION
        assert table_dump(second, "sqlite_master") == tables_before
    finally:
        second.close()


def test_a_newer_store_is_refused_by_name(tmp_path):
    path = tmp_path / "store.db"
    raw = sqlite3.connect(path)
    raw.execute("PRAGMA user_version=7")
    raw.close()
    with pytest.raises(store.StoreVersionError) as caught:
        store.open_store(path)
    message = str(caught.value)
    assert "7" in message and str(schema.SCHEMA_VERSION) in message and str(path) in message


def test_an_older_store_with_no_migration_step_is_refused_by_name(tmp_path, monkeypatch):
    """The hook exists before any step does: a version 2 tool opening a version 1 file
    must find MIGRATIONS[2] or say so, never silently read it."""
    path = tmp_path / "store.db"
    store.open_store(path).close()                       # a version-1 file
    monkeypatch.setattr(store, "SCHEMA_VERSION", 2)
    monkeypatch.setattr(schema, "SCHEMA_VERSION", 2)
    with pytest.raises(store.StoreVersionError) as caught:
        store.open_store(path)
    assert "no migration step to 2" in str(caught.value)


def test_a_migration_step_runs_and_stamps_the_new_version(tmp_path, monkeypatch):
    path = tmp_path / "store.db"
    store.open_store(path).close()
    ran = []
    monkeypatch.setattr(store, "SCHEMA_VERSION", 2)
    monkeypatch.setattr(schema, "SCHEMA_VERSION", 2)
    monkeypatch.setitem(schema.MIGRATIONS, 2, lambda conn: ran.append(2))
    conn = store.open_store(path)
    try:
        assert ran == [2]
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    finally:
        conn.close()


def test_the_store_lands_under_the_config_dir_with_no_patching():
    """ED_CONFIG_DIR (set by the conftest) is the whole of the redirection."""
    expected = Path(os.environ["ED_CONFIG_DIR"]) / "store.db"
    assert store.store_path() == expected
    assert not expected.exists()
    store.open_store().close()
    assert expected.is_file()


def test_the_path_is_resolved_per_call(tmp_path, monkeypatch):
    monkeypatch.setenv("ED_CONFIG_DIR", str(tmp_path / "one"))
    store.open_store().close()
    monkeypatch.setenv("ED_CONFIG_DIR", str(tmp_path / "two"))
    store.open_store().close()
    assert (tmp_path / "one" / "store.db").is_file()
    assert (tmp_path / "two" / "store.db").is_file()


# --------------------------------------------------------------------------
# verify
# --------------------------------------------------------------------------

def test_a_fresh_store_verifies_clean(tmp_path):
    conn = store.open_store(tmp_path / "store.db")
    try:
        assert store.verify(conn) == []
    finally:
        conn.close()


def test_an_orphaned_observation_fails_verify(tmp_path):
    conn = store.open_store(tmp_path / "store.db")
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            "INSERT INTO observations (source_id, kind, observed_at, recorded_at, "
            "content_sha256, payload) VALUES (999, 'market_json', 't', 't', 'h', x'00')")
        conn.commit()
        problems = store.verify(conn)
        assert any("observations" in p and "sources" in p for p in problems), problems
    finally:
        conn.close()


def test_an_unregistered_table_fails_verify(tmp_path):
    """The registry fails closed, the way generated.py's does."""
    conn = store.open_store(tmp_path / "store.db")
    try:
        conn.execute("CREATE TABLE stray (x INTEGER)")
        conn.commit()
        problems = store.verify(conn)
        assert any("stray" in p and "not registered" in p for p in problems), problems
    finally:
        conn.close()


def test_a_missing_registered_table_fails_verify(tmp_path):
    conn = store.open_store(tmp_path / "store.db")
    try:
        conn.execute("DROP TABLE writes")
        conn.commit()
        assert any("writes" in p and "missing" in p for p in store.verify(conn))
    finally:
        conn.close()


def test_a_corrupt_file_fails_verify_on_integrity(tmp_path):
    path = tmp_path / "store.db"
    conn = store.open_store(path)
    plant_market(conn)                               # enough pages to lose one
    conn.close()
    data = path.read_bytes()
    path.write_bytes(data[: len(data) // 2])         # the tail of the file is gone
    conn = sqlite3.connect(path)
    try:
        problems = store.verify(conn)
        assert problems and problems[0].startswith("integrity_check")
    finally:
        conn.close()


# --------------------------------------------------------------------------
# backup
# --------------------------------------------------------------------------

def test_backup_writes_a_copy_that_opens_and_verifies(tmp_path):
    conn = store.open_store(tmp_path / "store.db")
    try:
        plant_market(conn)
        copy = store.backup(conn, stamp="20260925T034500Z")
    finally:
        conn.close()
    assert copy == tmp_path / "store.db.bak-20260925T034500Z"
    restored = store.open_store(copy)
    try:
        assert store.verify(restored) == []
        assert restored.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
    finally:
        restored.close()


def test_backup_is_refused_when_verify_fails_and_writes_nothing(tmp_path):
    conn = store.open_store(tmp_path / "store.db")
    try:
        conn.execute("CREATE TABLE stray (x INTEGER)")
        conn.commit()
        with pytest.raises(store.StoreError) as caught:
            store.backup(conn, stamp="x")
        assert "refused" in str(caught.value) and "stray" in str(caught.value)
    finally:
        conn.close()
    assert not (tmp_path / "store.db.bak-x").exists()


# --------------------------------------------------------------------------
# rebuild
# --------------------------------------------------------------------------

def test_rebuild_restores_a_deleted_projection_and_leaves_primary_tables_alone(tmp_path):
    conn = store.open_store(tmp_path / "store.db")
    try:
        obs_id = plant_market(conn)
        primary_before = {t.name: table_dump(conn, t.name) for t in registry.primary()}
        items_before = table_dump(conn, "market_item")
        assert len(items_before) == 2

        conn.execute("DELETE FROM market_item")
        conn.execute("DELETE FROM market_snapshot")
        conn.commit()
        assert table_dump(conn, "market_snapshot") == []

        rebuilt = store.rebuild(conn)

        # The primary tables first: that is the promise, the rest is the mechanism.
        assert {t.name: table_dump(conn, t.name) for t in registry.primary()} == primary_before
        assert set(rebuilt) == {"market_snapshot", "market_item"}
        assert table_dump(conn, "market_item") == items_before
        assert conn.execute("SELECT obs_id, station FROM market_snapshot").fetchone() == \
            (obs_id, "Ryman Enterprise")
        assert {t.name: table_dump(conn, t.name) for t in registry.primary()} == primary_before
        assert store.verify(conn) == []
    finally:
        conn.close()


def test_rebuild_refuses_by_name_when_nothing_is_derived(tmp_path, monkeypatch):
    conn = store.open_store(tmp_path / "store.db")
    try:
        monkeypatch.setattr(registry, "derived", lambda: ())
        with pytest.raises(store.StoreError) as caught:
            store.rebuild(conn)
        assert "nothing derived" in str(caught.value)
    finally:
        conn.close()


# --------------------------------------------------------------------------
# archive (the function the readers call) and the market projection
# --------------------------------------------------------------------------

def test_archiving_the_same_bytes_twice_adds_one_observation(tmp_path):
    conn = store.open_store(tmp_path / "store.db")
    try:
        first = plant_market(conn)
        second = plant_market(conn)
        assert first == second
        assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 1
    finally:
        conn.close()


def test_different_bytes_add_a_second_observation_and_source(tmp_path):
    conn = store.open_store(tmp_path / "store.db")
    try:
        plant_market(conn)
        plant_market(conn, market_bytes(timestamp="2026-09-08T04:00:00Z"))
        assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM market_snapshot").fetchone()[0] == 2
        # same path, different content: a different source row, marked absent
        rows = conn.execute("SELECT liveness FROM sources").fetchall()
        assert rows == [("absent",), ("absent",)]
    finally:
        conn.close()


def test_the_source_row_carries_commander_name_and_fid(tmp_path):
    conn = store.open_store(tmp_path / "store.db")
    try:
        plant_market(conn)
        row = conn.execute(
            "SELECT kind, machine, commander, commander_fid, locator FROM sources").fetchone()
        assert row == ("market_json", "plzwork", "Extreme", "F1234", "C:/journal/Market.json")
    finally:
        conn.close()


def test_the_projection_speaks_commodity_v3(tmp_path):
    conn = store.open_store(tmp_path / "store.db")
    try:
        plant_market(conn)
        snap = conn.execute(
            "SELECT market_id, station, system, station_type, observed_at, items_count "
            "FROM market_snapshot").fetchone()
        assert snap == (3226578176, "Ryman Enterprise", "Lhou Mans", "Coriolis",
                        "2026-09-08T03:13:00Z", 2)
        items = conn.execute(
            "SELECT name, symbol, meanPrice, buyPrice, stock, stockBracket, sellPrice, demand, "
            "demandBracket, statusFlags FROM market_item ORDER BY name").fetchall()
        assert items == [
            ("gold", "$gold_name;", 9401, 0, 0, 0, 9401, 42, 2, "Consumer"),
            ("palladium", "$palladium_name;", 13, 13, 999, 3, 12, 0, 0, "Producer"),
        ]
    finally:
        conn.close()


def test_an_empty_market_projects_to_a_valid_snapshot(tmp_path):
    """A fleet carrier with no orders is a market with zero items, not no market."""
    conn = store.open_store(tmp_path / "store.db")
    try:
        plant_market(conn, market_bytes(Items=[]))
        assert conn.execute("SELECT items_count FROM market_snapshot").fetchone() == (0,)
    finally:
        conn.close()


def test_a_rare_commodity_keeps_its_flag(tmp_path):
    """Rare goods are the one status the journal marks that a price alone cannot show."""
    conn = store.open_store(tmp_path / "store.db")
    try:
        rare = {**MARKET_JSON["Items"][0], "Name": "$lavianbrandy_name;", "Rare": True,
                "Producer": False}
        plant_market(conn, market_bytes(Items=[rare]))
        assert conn.execute("SELECT statusFlags FROM market_item").fetchone() == ("Rare",)
    finally:
        conn.close()


def test_a_market_without_an_id_is_kept_raw_and_projects_nothing(tmp_path):
    """No MarketID means nothing to key a snapshot on; the bytes still count as a round."""
    conn = store.open_store(tmp_path / "store.db")
    try:
        payload = {k: v for k, v in MARKET_JSON.items() if k != "MarketID"}
        obs_id = store.archive("market_json", json.dumps(payload).encode("utf-8"),
                               locator="x", conn=conn)
        assert obs_id is not None
        assert conn.execute("SELECT COUNT(*) FROM market_snapshot").fetchone()[0] == 0
        assert store.verify(conn) == []
    finally:
        conn.close()


def test_projecting_one_market_leaves_another_markets_items_alone(tmp_path):
    conn = store.open_store(tmp_path / "store.db")
    try:
        first = plant_market(conn)
        second = plant_market(conn, market_bytes(MarketID=4323280387, timestamp="2026-09-08T04:00:00Z"))
        counts = dict(conn.execute(
            "SELECT obs_id, COUNT(*) FROM market_item GROUP BY obs_id").fetchall())
        assert counts == {first: 2, second: 2}
    finally:
        conn.close()


def test_bytes_that_do_not_parse_are_kept_raw_and_project_nothing(tmp_path):
    conn = store.open_store(tmp_path / "store.db")
    try:
        obs_id = store.archive("market_json", b"{not json", locator="x", conn=conn)
        assert obs_id is not None
        assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM market_snapshot").fetchone()[0] == 0
        assert store.verify(conn) == []
    finally:
        conn.close()


def test_archive_never_raises_and_reports_once(tmp_path, monkeypatch, capsys):
    """The store is additive: a failure to record must not fail the command."""
    monkeypatch.setattr(store, "open_store", lambda path=None: (_ for _ in ()).throw(
        sqlite3.OperationalError("disk full")))
    settings._reported.clear()
    assert store.archive("market_json", b"{}", locator="x") is None
    assert store.archive("market_json", b"{}", locator="x") is None
    err = capsys.readouterr().err
    assert err.count("could not archive") == 1 and "disk full" in err


def test_canonical_names_follow_edmc():
    assert canonical_name("$gold_name;") == "gold"
    assert canonical_name("$Palladium_name;") == "palladium"
    assert canonical_name("gold") == "gold"
    assert canonical_name("") == ""


def test_rows_from_market_json_keeps_the_symbol_beside_the_name():
    snapshot, items = rows_from_market_json(MARKET_JSON)
    assert snapshot["items_count"] == 2
    assert items[0]["symbol"] == "$palladium_name;" and items[0]["name"] == "palladium"


# --------------------------------------------------------------------------
# the docs
# --------------------------------------------------------------------------

def test_the_docs_describe_the_store_its_verbs_and_the_tiers():
    root = Path(__file__).resolve().parent.parent
    page = (root / "docs" / "store.md").read_text(encoding="utf-8")
    for word in ("store.db", "verify", "backup", "rebuild", "primary", "derived",
                 "ED_NO_STORE", "construction"):
        assert word in page, f"docs/store.md does not mention {word}"
    files = (root / "docs" / "configuration.md").read_text(encoding="utf-8")
    assert "store.db" in files
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "docs/store.md" in readme
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [0.7.9]" in changelog and "store verify" in changelog


# --------------------------------------------------------------------------
# the CLI
# --------------------------------------------------------------------------

def test_store_verify_on_a_fresh_install_writes_no_config_and_no_store(capsys):
    config_dir = Path(os.environ["ED_CONFIG_DIR"])
    assert main(["store", "verify"]) == 0
    out = capsys.readouterr().out
    assert "No store at" in out
    assert sorted(p.name for p in config_dir.iterdir()) == []


def test_store_backup_and_rebuild_need_a_store(capsys):
    assert main(["store", "backup"]) == 2
    assert main(["store", "rebuild"]) == 2


def test_store_verify_reports_ok_and_problems(capsys):
    conn = store.open_store()
    conn.close()
    assert main(["store", "verify"]) == 0
    assert "Store OK" in capsys.readouterr().out

    conn = store.open_store()
    conn.execute("CREATE TABLE stray (x INTEGER)")
    conn.commit()
    conn.close()
    assert main(["store", "verify"]) == 1
    out = capsys.readouterr().out
    assert "1 problem" in out and "stray" in out


def test_store_backup_and_rebuild_through_the_cli(capsys):
    conn = store.open_store()
    plant_market(conn)
    conn.close()
    assert main(["store", "backup"]) == 0
    line = capsys.readouterr().out
    assert "Backed up to" in line and ".bak-" in line
    assert main(["store", "rebuild"]) == 0
    assert "market_snapshot" in capsys.readouterr().out


def test_store_refuses_a_newer_file_through_the_cli(capsys):
    path = store.store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(path)
    raw.execute("PRAGMA user_version=7")
    raw.close()
    assert main(["store", "verify"]) == 1
    assert "newer than" in capsys.readouterr().err
