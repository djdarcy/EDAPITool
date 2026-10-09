"""
The derived tables read from journal observations, and the one door every
projection goes through (the store design of 2026-10-09, unit 3; #22's
criteria 3, 11, 12 and 19).

``project_one`` is called as a raw row is kept -- by ``archive`` for a side
file, by the ingest for a journal line -- and ``project_all`` is what
``rebuild`` runs; both read only ``observations`` and write only tables
registered DERIVED, so a rebuild reproduces them exactly. A row that does
not parse projects to nothing; the raw bytes are still there.

What is derived, and from which event (the survey of EDDiscovery and EDMC
chose the columns -- the references note of 2026-10-09):

``system`` and ``station``
    Identity, keyed on SystemAddress and MarketID. The name is an
    attribute, with every name seen kept in order in ``name_history``, so
    a renamed system or station is one row (criterion 12).
``faction_presence`` and ``conflict``
    One row per (observation, faction) from every event carrying
    ``Factions[]`` -- Location, FSDJump, CarrierJump -- with influence,
    state, government, allegiance, happiness, the three state lists as
    JSON, and whether the faction controls the system; conflicts as
    sibling rows. Every reading is kept, which is the point: the delta
    over time is what the BGS criteria ask for.
``construction_reading``, ``construction_contribution``, ``construction_delta``
    One reading row per depot event per resource, with the event's
    progress, complete and failed beside each; one contribution row per
    resource the commander handed in; and per site the lifetime delta:
    ``delivered`` is the site's total provided at its highest reading
    minus at its lowest (the proof of concept's definition, which gave
    269,924 t for site 3957057282), ``own`` the commander's contributions,
    ``by_others`` the difference (criterion 19).
``trade``
    Every MarketBuy, MarketSell and CargoTransfer, the symbol resolved
    through the commodity catalog; an unknown symbol is kept raw and
    flagged (criterion 11). The design called this table ``transaction``;
    SQL already owns that word.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable, Optional

from .market import MARKET_KINDS, canonical_name
from .market import project_one as _project_market

LOCATION_KINDS = ("location", "fsdjump", "carrierjump")
DEPOT = "colonisationconstructiondepot"
CONTRIBUTION = "colonisationcontribution"
TRADE_KINDS = ("marketbuy", "marketsell", "cargotransfer")
#: Every journal kind a derived table reads.
JOURNAL_KINDS = LOCATION_KINDS + ("docked", DEPOT, CONTRIBUTION) + TRADE_KINDS


def _parse(payload: bytes) -> Optional[dict]:
    try:
        parsed = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _real(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# -- identity ----------------------------------------------------------------------

def _with_name(history_json: Optional[str], name: str) -> str:
    history = json.loads(history_json) if history_json else []
    if name not in history:
        history.append(name)
    return json.dumps(history)


def _system(conn: sqlite3.Connection, event: dict, observed_at: str) -> bool:
    address = _int(event.get("SystemAddress"))
    name = event.get("StarSystem")
    if address is None or not name:
        return False
    pos = event.get("StarPos") or [None, None, None]
    x, y, z = (_real(v) for v in (list(pos) + [None] * 3)[:3])
    row = conn.execute(
        "SELECT name, first_seen, last_seen, name_history FROM system WHERE system_address = ?",
        (address,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO system (system_address, name, x, y, z, first_seen, last_seen, "
            "name_history, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'journal')",
            (address, name, x, y, z, observed_at, observed_at, json.dumps([name])))
        return True
    old_name, first, last, history = row
    newest = observed_at >= last
    conn.execute(
        "UPDATE system SET name = ?, x = COALESCE(?, x), y = COALESCE(?, y), z = COALESCE(?, z), "
        "first_seen = MIN(first_seen, ?), last_seen = MAX(last_seen, ?), name_history = ? "
        "WHERE system_address = ?",
        (name if newest else old_name, x, y, z, observed_at, observed_at,
         _with_name(history, name), address))
    return True


def _station(conn: sqlite3.Connection, event: dict, observed_at: str) -> bool:
    if event.get("event") == "Location" and not event.get("Docked"):
        return False
    market_id = _int(event.get("MarketID"))
    name = event.get("StationName")
    if market_id is None or not name:
        return False
    address = _int(event.get("SystemAddress"))
    kind = event.get("StationType")
    row = conn.execute(
        "SELECT name, last_seen, name_history FROM station WHERE market_id = ?",
        (market_id,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO station (market_id, system_address, name, type, first_seen, last_seen, "
            "name_history) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (market_id, address, name, kind, observed_at, observed_at, json.dumps([name])))
        return True
    old_name, last, history = row
    newest = observed_at >= last
    conn.execute(
        "UPDATE station SET name = ?, system_address = COALESCE(?, system_address), "
        "type = COALESCE(?, type), first_seen = MIN(first_seen, ?), last_seen = MAX(last_seen, ?), "
        "name_history = ? WHERE market_id = ?",
        (name if newest else old_name, address, kind, observed_at, observed_at,
         _with_name(history, name), market_id))
    return True


# -- the BGS -------------------------------------------------------------------------

def _states(faction: dict, key: str) -> Optional[str]:
    states = faction.get(key)
    return json.dumps(states) if states else None


def _factions(conn: sqlite3.Connection, obs_id: int, event: dict, observed_at: str) -> bool:
    address = _int(event.get("SystemAddress"))
    factions = event.get("Factions")
    if address is None or not isinstance(factions, list):
        return False
    # Older journals wrote the system faction as a bare name; newer ones as
    # an object with its state beside it.
    system_faction = event.get("SystemFaction")
    if isinstance(system_faction, dict):
        controlling = system_faction.get("Name")
    else:
        controlling = system_faction if isinstance(system_faction, str) else None
    rows = []
    for faction in factions:
        if not isinstance(faction, dict) or not faction.get("Name"):
            continue
        rows.append((
            obs_id, address, faction["Name"], observed_at,
            _real(faction.get("Influence")), faction.get("FactionState"),
            faction.get("Government"), faction.get("Allegiance"), faction.get("Happiness"),
            _real(faction.get("MyReputation")),
            1 if faction["Name"] == controlling else 0,
            _states(faction, "ActiveStates"), _states(faction, "PendingStates"),
            _states(faction, "RecoveringStates"),
        ))
    conn.executemany(
        "INSERT OR REPLACE INTO faction_presence (obs_id, system_address, faction, observed_at, "
        "influence, state, government, allegiance, happiness, my_reputation, controlling, "
        "active, pending, recovering) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conflicts = []
    for conflict in event.get("Conflicts") or []:
        if not isinstance(conflict, dict):
            continue
        one = conflict.get("Faction1") or {}
        two = conflict.get("Faction2") or {}
        conflicts.append((
            obs_id, address, observed_at, conflict.get("WarType"), conflict.get("Status"),
            one.get("Name"), one.get("Stake"), _int(one.get("WonDays")),
            two.get("Name"), two.get("Stake"), _int(two.get("WonDays")),
        ))
    conn.executemany(
        "INSERT OR REPLACE INTO conflict (obs_id, system_address, observed_at, war_type, status, "
        "faction1, faction1_stake, faction1_won_days, faction2, faction2_stake, faction2_won_days) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", conflicts)
    return bool(rows or conflicts)


# -- construction ----------------------------------------------------------------------

def _reading(conn: sqlite3.Connection, obs_id: int, event: dict, observed_at: str) -> Optional[int]:
    market_id = _int(event.get("MarketID"))
    resources = event.get("ResourcesRequired")
    if market_id is None or not isinstance(resources, list):
        return None
    progress = _real(event.get("ConstructionProgress"))
    complete = 1 if event.get("ConstructionComplete") else 0
    failed = 1 if event.get("ConstructionFailed") else 0
    rows = []
    for resource in resources:
        if not isinstance(resource, dict) or not resource.get("Name"):
            continue
        rows.append((obs_id, market_id, observed_at, canonical_name(resource["Name"]),
                     resource.get("Name_Localised"), _int(resource.get("RequiredAmount")),
                     _int(resource.get("ProvidedAmount")), _int(resource.get("Payment")),
                     progress, complete, failed))
    conn.executemany(
        "INSERT OR REPLACE INTO construction_reading (obs_id, market_id, observed_at, symbol, "
        "name_localised, required, provided, payment, progress, complete, failed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return market_id


def _contribution(conn: sqlite3.Connection, obs_id: int, event: dict, observed_at: str) -> Optional[int]:
    market_id = _int(event.get("MarketID"))
    contributions = event.get("Contributions")
    if market_id is None or not isinstance(contributions, list):
        return None
    rows = [(obs_id, market_id, observed_at, canonical_name(c["Name"]), _int(c.get("Amount")))
            for c in contributions if isinstance(c, dict) and c.get("Name")]
    conn.executemany(
        "INSERT OR REPLACE INTO construction_contribution (obs_id, market_id, observed_at, "
        "symbol, amount) VALUES (?, ?, ?, ?, ?)", rows)
    return market_id


def delta(conn: sqlite3.Connection, market_id: int) -> bool:
    """Recompute one site's row of ``construction_delta`` from its readings and contributions."""
    readings, first, last, low, high = conn.execute(
        "WITH totals AS (SELECT obs_id, observed_at, SUM(provided) AS provided "
        "FROM construction_reading WHERE market_id = ? GROUP BY obs_id, observed_at) "
        "SELECT COUNT(*), MIN(observed_at), MAX(observed_at), MIN(provided), MAX(provided) "
        "FROM totals", (market_id,)).fetchone()
    if not readings:
        conn.execute("DELETE FROM construction_delta WHERE market_id = ?", (market_id,))
        return False
    own, contributions = conn.execute(
        "SELECT COALESCE(SUM(amount), 0), COUNT(DISTINCT obs_id) FROM construction_contribution "
        "WHERE market_id = ?", (market_id,)).fetchone()
    progress, complete, failed = conn.execute(
        "SELECT progress, complete, failed FROM construction_reading WHERE market_id = ? "
        "ORDER BY observed_at DESC, obs_id DESC LIMIT 1", (market_id,)).fetchone()
    delivered = int(high) - int(low)
    conn.execute(
        "INSERT OR REPLACE INTO construction_delta (market_id, readings, first_seen, last_seen, "
        "provided_low, provided_high, delivered, own, by_others, contributions, progress, "
        "complete, failed) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (market_id, readings, first, last, int(low), int(high), delivered, int(own),
         delivered - int(own), contributions, progress, complete, failed))
    return True


# -- trades ------------------------------------------------------------------------------

def _trade_rows(obs_id: int, kind: str, event: dict, observed_at: str) -> list[tuple]:
    from ..catalog import load_catalog

    catalog = load_catalog()

    def resolved(symbol: str):
        found = catalog.resolve(symbol=symbol)
        return (found.name, found.id, 0) if found is not None else (None, None, 1)

    market_id = _int(event.get("MarketID"))
    if kind == "cargotransfer":
        rows = []
        for transfer in event.get("Transfers") or []:
            if not isinstance(transfer, dict) or not transfer.get("Type"):
                continue
            direction = f"transfer:{transfer.get('Direction') or '?'}"
            name, commodity_id, unknown = resolved(transfer["Type"])
            rows.append((obs_id, market_id, observed_at, direction, transfer["Type"], name,
                         commodity_id, _int(transfer.get("Count")) or 0, None, None, unknown))
        return rows
    symbol = event.get("Type")
    if not symbol:
        return []
    name, commodity_id, unknown = resolved(symbol)
    if kind == "marketbuy":
        return [(obs_id, market_id, observed_at, "buy", symbol, name, commodity_id,
                 _int(event.get("Count")) or 0, _int(event.get("BuyPrice")),
                 _int(event.get("TotalCost")), unknown)]
    return [(obs_id, market_id, observed_at, "sell", symbol, name, commodity_id,
             _int(event.get("Count")) or 0, _int(event.get("SellPrice")),
             _int(event.get("TotalSale")), unknown)]


def _trade(conn: sqlite3.Connection, obs_id: int, kind: str, event: dict, observed_at: str) -> bool:
    rows = _trade_rows(obs_id, kind, event, observed_at)
    conn.executemany(
        "INSERT OR REPLACE INTO trade (obs_id, market_id, observed_at, direction, symbol, name, "
        "commodity_id, count, unit_price, total, unknown) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows)
    return bool(rows)


# -- the door ------------------------------------------------------------------------------

def project_one(conn: sqlite3.Connection, obs_id: int, kind: str, payload: bytes,
                observed_at: str, *, deltas: bool = True) -> bool:
    """
    Project one raw row into whatever derived tables read its kind.

    True when something was written. ``deltas=False`` leaves the per-site
    delta row for the caller to recompute once, which ``project_all`` does.
    """
    if kind in MARKET_KINDS:
        return _project_market(conn, obs_id, kind, payload, observed_at)
    if kind not in JOURNAL_KINDS:
        return False
    event = _parse(payload)
    if event is None:
        return False
    try:
        return _project_journal(conn, obs_id, kind, event, observed_at, deltas)
    except Exception as exc:          # a shape this code did not expect: the raw row is kept
        from .. import settings
        from . import store_path
        settings.report_once(store_path(), f"store: could not project {kind} (obs {obs_id}): {exc}")
        return False


def _project_journal(conn: sqlite3.Connection, obs_id: int, kind: str, event: dict,
                     observed_at: str, deltas: bool) -> bool:
    wrote = False
    if kind in LOCATION_KINDS:
        wrote |= _system(conn, event, observed_at)
        wrote |= _factions(conn, obs_id, event, observed_at)
    if kind in ("docked", "carrierjump", "location"):
        wrote |= _station(conn, event, observed_at)
    if kind in (DEPOT, CONTRIBUTION):
        site = (_reading if kind == DEPOT else _contribution)(conn, obs_id, event, observed_at)
        if site is not None:
            wrote = True
            if deltas:
                delta(conn, site)
    if kind in TRADE_KINDS:
        wrote |= _trade(conn, obs_id, kind, event, observed_at)
    return wrote


def project_all(conn: sqlite3.Connection) -> int:
    """
    Re-project every journal-derived table. Returns how many raw rows wrote something.

    Rows are walked in the order they were kept -- the ingest's order, the
    files oldest first -- not by timestamp, so a rebuild sees exactly the
    sequence the ingest saw and the name histories come out the same.
    """
    placeholders = ",".join("?" for _ in JOURNAL_KINDS)
    rows: Iterable = conn.execute(
        f"SELECT obs_id, kind, payload, observed_at FROM observations "
        f"WHERE kind IN ({placeholders}) ORDER BY obs_id", JOURNAL_KINDS).fetchall()
    written = 0
    for obs_id, kind, payload, observed_at in rows:
        if project_one(conn, obs_id, kind, payload, observed_at, deltas=False):
            written += 1
    for (site,) in conn.execute("SELECT DISTINCT market_id FROM construction_reading").fetchall():
        delta(conn, site)
    return written
