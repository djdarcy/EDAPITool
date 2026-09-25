"""
The market projection: raw market bytes re-read as rows.

Two kinds of raw row carry a market. ``market_json`` is the game's own
``Market.json`` (``Items`` with ``$gold_name;`` tokens and ``Consumer`` /
``Producer`` / ``Rare`` booleans); ``capi_market`` is Frontier's
``/market`` endpoint (``commodities`` with ``name`` already canonical and a
``statusFlags`` list). Both land in the same two tables under EDDN
commodity-v3.0 column names, which is the mapping EDMC ships and the one
every downstream tool already reads.

A row that does not parse projects to nothing and says so once; the raw
bytes are still there, which is the point of keeping them.
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Iterable, Optional

MARKET_KINDS = ("market_json", "capi_market")

# EDMC's CANONICALISE_RE: ``$gold_name;`` -> ``gold``. A name that is not
# in that form is kept as it is, lowercased, so a CAPI name passes through.
_TOKEN = re.compile(r"^\$(.+)_name;$")


def canonical_name(symbol: str) -> str:
    match = _TOKEN.match(symbol or "")
    return (match.group(1) if match else (symbol or "")).lower()


def _int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _flags_from_market_json(item: dict) -> Optional[str]:
    flags = [name for name in ("Consumer", "Producer", "Rare") if item.get(name)]
    return ",".join(flags) if flags else None


def rows_from_market_json(payload: dict) -> tuple[dict, list[dict]]:
    """The snapshot row and its item rows for one ``Market.json``."""
    items = payload.get("Items") or []
    snapshot = {
        "market_id": _int(payload.get("MarketID")),
        "station": payload.get("StationName"),
        "system": payload.get("StarSystem"),
        "station_type": payload.get("StationType"),
        "observed_at": payload.get("timestamp"),
        "items_count": len(items),
    }
    rows = []
    for item in items:
        symbol = item.get("Name") or ""
        rows.append({
            "name": canonical_name(symbol),
            "symbol": symbol,
            "name_localised": item.get("Name_Localised"),
            "category": item.get("Category_Localised") or item.get("Category"),
            "meanPrice": _int(item.get("MeanPrice")),
            "buyPrice": _int(item.get("BuyPrice")),
            "stock": _int(item.get("Stock")),
            "stockBracket": _int(item.get("StockBracket")),
            "sellPrice": _int(item.get("SellPrice")),
            "demand": _int(item.get("Demand")),
            "demandBracket": _int(item.get("DemandBracket")),
            "statusFlags": _flags_from_market_json(item),
        })
    return snapshot, rows


def rows_from_capi_market(payload: dict, observed_at: str) -> tuple[dict, list[dict]]:
    """The same two shapes for Frontier's ``/market`` payload."""
    items = payload.get("commodities") or []
    snapshot = {
        "market_id": _int(payload.get("id")),
        "station": payload.get("name"),
        "system": None,                     # /market does not say; /profile does
        "station_type": payload.get("outpostType"),
        "observed_at": observed_at,
        "items_count": len(items),
    }
    rows = []
    for item in items:
        name = item.get("name") or ""
        flags = item.get("statusFlags") or []
        rows.append({
            "name": name.lower(),
            "symbol": name,
            "name_localised": item.get("locName"),
            "category": item.get("categoryname"),
            "meanPrice": _int(item.get("meanPrice")),
            "buyPrice": _int(item.get("buyPrice")),
            "stock": _int(item.get("stock")),
            "stockBracket": _int(item.get("stockBracket")),
            "sellPrice": _int(item.get("sellPrice")),
            "demand": _int(item.get("demand")),
            "demandBracket": _int(item.get("demandBracket")),
            "statusFlags": ",".join(str(f) for f in flags) if flags else None,
        })
    return snapshot, rows


_SNAPSHOT_SQL = (
    "INSERT OR REPLACE INTO market_snapshot "
    "(obs_id, market_id, station, system, station_type, observed_at, items_count) "
    "VALUES (:obs_id, :market_id, :station, :system, :station_type, :observed_at, :items_count)"
)
_ITEM_SQL = (
    "INSERT OR REPLACE INTO market_item "
    "(obs_id, name, symbol, name_localised, category, meanPrice, buyPrice, stock, "
    "stockBracket, sellPrice, demand, demandBracket, statusFlags) "
    "VALUES (:obs_id, :name, :symbol, :name_localised, :category, :meanPrice, :buyPrice, "
    ":stock, :stockBracket, :sellPrice, :demand, :demandBracket, :statusFlags)"
)


def project_one(conn: sqlite3.Connection, obs_id: int, kind: str,
                payload: bytes, observed_at: str) -> bool:
    """
    Project one raw row. True when a snapshot was written.

    False means the bytes did not parse as the kind claims, or the kind is
    not a market at all; the raw row is untouched either way.
    """
    if kind not in MARKET_KINDS:
        return False
    try:
        parsed = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return False
    if not isinstance(parsed, dict):
        return False
    if kind == "market_json":
        snapshot, items = rows_from_market_json(parsed)
    else:
        snapshot, items = rows_from_capi_market(parsed, observed_at)
    if snapshot["market_id"] is None:
        return False
    snapshot["observed_at"] = snapshot["observed_at"] or observed_at
    snapshot["obs_id"] = obs_id
    conn.execute("DELETE FROM market_item WHERE obs_id = ?", (obs_id,))
    conn.execute(_SNAPSHOT_SQL, snapshot)
    conn.executemany(_ITEM_SQL, [{**row, "obs_id": obs_id} for row in items])
    return True


def project_all(conn: sqlite3.Connection) -> int:
    """Re-project every raw market row. Returns how many snapshots were written."""
    placeholders = ",".join("?" for _ in MARKET_KINDS)
    rows: Iterable = conn.execute(
        f"SELECT obs_id, kind, payload, observed_at FROM observations "
        f"WHERE kind IN ({placeholders}) ORDER BY obs_id",
        MARKET_KINDS,
    ).fetchall()
    written = 0
    for obs_id, kind, payload, observed_at in rows:
        if project_one(conn, obs_id, kind, payload, observed_at):
            written += 1
    return written
