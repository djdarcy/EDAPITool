"""
The store's tables, and which tier each one is in.

Two tiers, by recoverability -- the whole of the 2026-09-14 design in one
word each:

``primary``
    What the tool cannot get back once it is gone. The game overwrites
    ``Market.json`` the next time the commodity screen opens, so the bytes
    we read are the only copy anywhere; ``sources`` is the provenance that
    says where a row came from; ``writes`` will be the ledger of what the
    tool painted into a sheet. ``rebuild`` never touches these.

``derived``
    A projection of primary rows into a shape that is convenient to query.
    ``market_snapshot`` and ``market_item`` are the ``Market.json`` bytes
    re-read as columns. Losing them costs nothing but a ``rebuild``.

Every table is registered with ``registry`` here, at import, so ``verify``
can fail closed on a table it does not know and ``rebuild`` can name exactly
what it may drop. A table added to this module without a registration is
a defect ``verify`` reports, not one it tolerates.

The one raw table -- ``observations`` -- is deliberately shaped so that a
new kind of data is a new *row*, not a new table: ``kind`` names what was
read, ``subject`` names the thing it was about, ``payload`` is the bytes as
read. Typed projections are added as their consumers arrive.
"""

from __future__ import annotations

from .registry import DERIVED, PRIMARY, register

#: The schema this code writes and reads. A file whose ``PRAGMA
#: user_version`` is higher was made by a newer tool and is refused; one
#: that is lower is migrated by the steps in ``MIGRATIONS``. Version 2
#: (2026-10-09) added the journal-derived tables below ``market_item``.
SCHEMA_VERSION = 2

STORE_DB = "store.db"


register("sources", PRIMARY, """
CREATE TABLE sources (
    source_id      INTEGER PRIMARY KEY,
    kind           TEXT    NOT NULL,
    machine        TEXT    NOT NULL,
    commander      TEXT,
    commander_fid  TEXT,
    locator        TEXT    NOT NULL,
    identity_hash  TEXT    NOT NULL,
    first_seen     TEXT    NOT NULL,
    last_verified  TEXT    NOT NULL,
    liveness       TEXT    NOT NULL DEFAULT 'present',
    events_yielded INTEGER NOT NULL DEFAULT 0,
    read_offset    INTEGER NOT NULL DEFAULT 0,
    ingested_bytes INTEGER NOT NULL DEFAULT 0,
    game_version   TEXT,
    game_build     TEXT,
    UNIQUE (machine, locator, identity_hash)
)
""")

register("observations", PRIMARY, """
CREATE TABLE observations (
    obs_id         INTEGER PRIMARY KEY,
    source_id      INTEGER NOT NULL REFERENCES sources (source_id),
    kind           TEXT    NOT NULL,
    subject        TEXT,
    observed_at    TEXT    NOT NULL,
    recorded_at    TEXT    NOT NULL,
    content_sha256 TEXT    NOT NULL,
    payload        BLOB    NOT NULL,
    UNIQUE (kind, content_sha256)
)
""")

# Reserved: the ledger of what the tool wrote where, so the next run can
# tell its own paint from a person's. No writer in this slice; primary so
# that a rebuild can never regenerate -- and therefore never forge -- it.
register("writes", PRIMARY, """
CREATE TABLE writes (
    target     TEXT NOT NULL,
    tab        TEXT NOT NULL,
    a1         TEXT NOT NULL,
    value      TEXT,
    written_at TEXT NOT NULL,
    run_id     TEXT,
    PRIMARY KEY (target, tab, a1)
)
""")


def _project_markets(conn) -> None:
    from .market import project_all
    project_all(conn)


register("market_snapshot", DERIVED, """
CREATE TABLE market_snapshot (
    obs_id       INTEGER PRIMARY KEY REFERENCES observations (obs_id),
    market_id    INTEGER NOT NULL,
    station      TEXT,
    system       TEXT,
    station_type TEXT,
    observed_at  TEXT    NOT NULL,
    items_count  INTEGER NOT NULL
)
""", projector=_project_markets)

# Column names are EDDN commodity-v3.0's on purpose: the schema everyone
# else already speaks. ``symbol`` keeps the game's own token
# (``$gold_name;``) beside the canonical ``name`` (``gold``).
register("market_item", DERIVED, """
CREATE TABLE market_item (
    obs_id        INTEGER NOT NULL REFERENCES market_snapshot (obs_id),
    name          TEXT    NOT NULL,
    symbol        TEXT    NOT NULL,
    name_localised TEXT,
    category      TEXT,
    meanPrice     INTEGER,
    buyPrice      INTEGER,
    stock         INTEGER,
    stockBracket  INTEGER,
    sellPrice     INTEGER,
    demand        INTEGER,
    demandBracket INTEGER,
    statusFlags   TEXT,
    PRIMARY KEY (obs_id, name)
)
""")


def _project_journal(conn) -> None:
    from .projections import project_all
    project_all(conn)


# The journal-derived tables (schema version 2). The projector is registered
# on the first of the group and fills all of them; what each holds and which
# event it reads is in ``projections.py``.

register("system", DERIVED, """
CREATE TABLE system (
    system_address INTEGER PRIMARY KEY,
    name           TEXT    NOT NULL,
    x              REAL,
    y              REAL,
    z              REAL,
    first_seen     TEXT    NOT NULL,
    last_seen      TEXT    NOT NULL,
    name_history   TEXT    NOT NULL,
    source         TEXT    NOT NULL DEFAULT 'journal'
)
""", projector=_project_journal)

register("station", DERIVED, """
CREATE TABLE station (
    market_id      INTEGER PRIMARY KEY,
    system_address INTEGER,
    name           TEXT    NOT NULL,
    type           TEXT,
    first_seen     TEXT    NOT NULL,
    last_seen      TEXT    NOT NULL,
    name_history   TEXT    NOT NULL
)
""")

register("faction_presence", DERIVED, """
CREATE TABLE faction_presence (
    obs_id         INTEGER NOT NULL REFERENCES observations (obs_id),
    system_address INTEGER NOT NULL,
    faction        TEXT    NOT NULL,
    observed_at    TEXT    NOT NULL,
    influence      REAL,
    state          TEXT,
    government     TEXT,
    allegiance     TEXT,
    happiness      TEXT,
    my_reputation  REAL,
    controlling    INTEGER NOT NULL DEFAULT 0,
    active         TEXT,
    pending        TEXT,
    recovering     TEXT,
    PRIMARY KEY (obs_id, faction)
)
""")

register("conflict", DERIVED, """
CREATE TABLE conflict (
    obs_id            INTEGER NOT NULL REFERENCES observations (obs_id),
    system_address    INTEGER NOT NULL,
    observed_at       TEXT    NOT NULL,
    war_type          TEXT,
    status            TEXT,
    faction1          TEXT,
    faction1_stake    TEXT,
    faction1_won_days INTEGER,
    faction2          TEXT,
    faction2_stake    TEXT,
    faction2_won_days INTEGER,
    PRIMARY KEY (obs_id, faction1, faction2)
)
""")

register("construction_reading", DERIVED, """
CREATE TABLE construction_reading (
    obs_id         INTEGER NOT NULL REFERENCES observations (obs_id),
    market_id      INTEGER NOT NULL,
    observed_at    TEXT    NOT NULL,
    symbol         TEXT    NOT NULL,
    name_localised TEXT,
    required       INTEGER,
    provided       INTEGER,
    payment        INTEGER,
    progress       REAL,
    complete       INTEGER NOT NULL DEFAULT 0,
    failed         INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (obs_id, symbol)
)
""")

register("construction_contribution", DERIVED, """
CREATE TABLE construction_contribution (
    obs_id      INTEGER NOT NULL REFERENCES observations (obs_id),
    market_id   INTEGER NOT NULL,
    observed_at TEXT    NOT NULL,
    symbol      TEXT    NOT NULL,
    amount      INTEGER,
    PRIMARY KEY (obs_id, symbol)
)
""")

register("construction_delta", DERIVED, """
CREATE TABLE construction_delta (
    market_id     INTEGER PRIMARY KEY,
    readings      INTEGER NOT NULL,
    first_seen    TEXT    NOT NULL,
    last_seen     TEXT    NOT NULL,
    provided_low  INTEGER NOT NULL,
    provided_high INTEGER NOT NULL,
    delivered     INTEGER NOT NULL,
    own           INTEGER NOT NULL,
    by_others     INTEGER NOT NULL,
    contributions INTEGER NOT NULL,
    progress      REAL,
    complete      INTEGER NOT NULL DEFAULT 0,
    failed        INTEGER NOT NULL DEFAULT 0
)
""")

register("trade", DERIVED, """
CREATE TABLE trade (
    obs_id       INTEGER NOT NULL REFERENCES observations (obs_id),
    market_id    INTEGER,
    observed_at  TEXT    NOT NULL,
    direction    TEXT    NOT NULL,
    symbol       TEXT    NOT NULL,
    name         TEXT,
    commodity_id INTEGER,
    count        INTEGER NOT NULL,
    unit_price   INTEGER,
    total        INTEGER,
    unknown      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (obs_id, symbol, direction)
)
""")

INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_observations_kind_subject "
    "ON observations (kind, subject, observed_at)",
    "CREATE INDEX IF NOT EXISTS ix_market_snapshot_market "
    "ON market_snapshot (market_id, observed_at)",
    "CREATE INDEX IF NOT EXISTS ix_station_system "
    "ON station (system_address)",
    "CREATE INDEX IF NOT EXISTS ix_faction_presence_system "
    "ON faction_presence (system_address, observed_at)",
    "CREATE INDEX IF NOT EXISTS ix_construction_reading_site "
    "ON construction_reading (market_id, observed_at)",
    "CREATE INDEX IF NOT EXISTS ix_construction_contribution_site "
    "ON construction_contribution (market_id, observed_at)",
    "CREATE INDEX IF NOT EXISTS ix_trade_market "
    "ON trade (market_id, observed_at)",
)


def _migrate_2(conn) -> None:
    """1 -> 2: create the journal-derived tables a version-1 store lacks, and fill them."""
    present = {name for (name,) in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    from . import registry as _registry
    for table in _registry.tables():
        if table.name not in present:
            conn.execute(table.ddl)
    for statement in INDEXES:
        conn.execute(statement)
    _project_journal(conn)


#: version -> callable(conn) that brings a store from version-1 to version.
#: ``open_store`` refuses, by name, any version it has no step for.
MIGRATIONS: dict = {2: _migrate_2}
