"""
``rebuild`` against the journal-derived tables (#22 criterion 3: the result
is identical to the pre-drop state), and the version-1 to version-2
migration that creates and fills them on open (criterion 15's first half).
"""

from test_store_projections import CONFLICT, FACTIONS, buy, contribution, depot, docked, fsdjump, ingest, sell, transfer

from APITool import cli
from APITool.store import open_store, rebuild, registry, store_path, verify
from APITool.store.schema import SCHEMA_VERSION

EVERYTHING = (
    fsdjump(2, name="Old Name", factions=FACTIONS, conflicts=(CONFLICT,), controlling="The Dark Wheel"),
    docked(3, "Site Alpha", market_id=3957057282),
    depot(4, [("steel", 1000, 60, 500), ("titanium", 500, 40, 900)]),
    contribution(5, [("steel", 50)]),
    depot(6, [("steel", 1000, 300, 500), ("titanium", 500, 50, 900)], progress=0.35),
    buy(7, "silver", 10, 100), sell(8, "frobnicator", 3, 7),
    transfer(9, [("gold", 5, "toship")]),
    fsdjump(10, name="New Name", factions=FACTIONS),
)


def _dump(conn) -> dict:
    out = {}
    for table in registry.derived():
        columns = [c[1] for c in conn.execute(f"PRAGMA table_info({table.name})")]
        order = ", ".join(columns)
        out[table.name] = conn.execute(f"SELECT {order} FROM {table.name} ORDER BY {order}").fetchall()
    return out


def test_rebuild_reproduces_every_derived_table_identically(tmp_path):
    """#22 criterion 3."""
    ingest(tmp_path, *EVERYTHING)
    conn = open_store(store_path())
    try:
        before = _dump(conn)
        for table in ("system", "station", "faction_presence", "conflict", "construction_reading",
                      "construction_contribution", "construction_delta", "trade"):
            assert before[table], f"{table} has rows to reproduce"
        rebuilt = rebuild(conn)
        after = _dump(conn)
        assert verify(conn) == []
    finally:
        conn.close()
    assert after == before
    assert rebuilt == [t.name for t in registry.derived()]


def test_the_rebuild_verb_names_every_derived_table(tmp_path, capsys):
    ingest(tmp_path, *EVERYTHING)

    assert cli.main(["store", "rebuild"]) == 0
    out = capsys.readouterr().out
    for table in ("market_snapshot", "system", "construction_delta", "trade"):
        assert table in out


def test_a_version_1_store_is_migrated_on_open_and_its_tables_filled(tmp_path):
    """#22 criterion 15, the one-version-old half."""
    ingest(tmp_path, *EVERYTHING)
    conn = open_store(store_path())
    try:
        before = _dump(conn)
        with conn:
            for table in reversed(registry.derived()):
                if table.name not in ("market_snapshot", "market_item"):
                    conn.execute(f"DROP TABLE {table.name}")
            conn.execute("PRAGMA user_version = 1")
    finally:
        conn.close()

    conn = open_store(store_path())
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 2
        assert verify(conn) == []
        assert _dump(conn) == before
    finally:
        conn.close()
