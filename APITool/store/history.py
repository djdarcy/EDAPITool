"""
The query seam: what a step may ask the store, as the supplier ``history``.

Core offers ``history`` on every pipeline (the market service's merge and
``pipeline.run_specs``), so a step declares ``needs = ("history",)`` and
pulls ``ctx.get("history")`` like any other supplier. The store is the
readers' memory -- the archive at read time, and the journal ingest -- and
this is the one door through which a step reads it (the design of
2026-10-09, "the store beside the pipelines").

Lazy on purpose: the store is opened on the first pull and never created
here. A run that pulls nothing opens nothing; a machine with no store yet
gets a ``History`` that answers empty, so a step written against this
seam runs the same on a fresh install.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Optional

NAME = "history"


@dataclass(frozen=True)
class Observation:
    """One kept read: what it was, of what, when, and the bytes themselves."""

    obs_id: int
    kind: str
    subject: Optional[str]
    observed_at: str
    payload: bytes


class History:
    """Read-only questions over an open store, or over nothing."""

    def __init__(self, conn: Optional[sqlite3.Connection]):
        self._conn = conn

    @classmethod
    def open(cls) -> "History":
        """The store at its configured path, when one exists; else an empty History."""
        from . import open_store, store_path

        path = store_path()
        if not path.is_file():
            return cls(None)
        return cls(open_store(path))

    @property
    def available(self) -> bool:
        return self._conn is not None

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # -- questions ----------------------------------------------------------

    def observations(self, kind: str, subject: Optional[str] = None, *,
                     since: Optional[str] = None, limit: int = 100) -> list[Observation]:
        """Kept reads of one kind, newest first, optionally of one subject and after a stamp."""
        if self._conn is None:
            return []
        where = ["kind = ?"]
        params: list[Any] = [kind]
        if subject is not None:
            where.append("subject = ?")
            params.append(str(subject))
        if since is not None:
            where.append("observed_at > ?")
            params.append(since)
        params.append(int(limit))
        rows = self._conn.execute(
            "SELECT obs_id, kind, subject, observed_at, payload FROM observations "
            f"WHERE {' AND '.join(where)} ORDER BY observed_at DESC, obs_id DESC LIMIT ?",
            params).fetchall()
        return [Observation(*row) for row in rows]

    def latest(self, kind: str, subject: Optional[str] = None) -> Optional[Observation]:
        """The newest kept read of one kind, optionally of one subject."""
        found = self.observations(kind, subject, limit=1)
        return found[0] if found else None

    def markets(self, market_id: int | str, *, limit: int = 20) -> list[dict]:
        """Market snapshots of one station, newest first, as the derived table has them."""
        if self._conn is None:
            return []
        rows = self._conn.execute(
            "SELECT obs_id, market_id, station, system, station_type, observed_at, items_count "
            "FROM market_snapshot WHERE market_id = ? ORDER BY observed_at DESC LIMIT ?",
            (int(market_id), int(limit))).fetchall()
        keys = ("obs_id", "market_id", "station", "system", "station_type", "observed_at", "items_count")
        return [dict(zip(keys, row)) for row in rows]

    def construction(self, site: int | str, *, limit: int = 100) -> list[Observation]:
        """Depot readings of one site, newest first, as the journal ingest recorded them."""
        return self.observations("colonisationconstructiondepot", str(site), limit=limit)

    def construction_delta(self, site: int | str) -> Optional[dict]:
        """One site's lifetime row: readings, delivered, own, by others, progress."""
        if self._conn is None:
            return None
        keys = ("market_id", "readings", "first_seen", "last_seen", "provided_low",
                "provided_high", "delivered", "own", "by_others", "contributions",
                "progress", "complete", "failed")
        row = self._conn.execute(
            f"SELECT {', '.join(keys)} FROM construction_delta WHERE market_id = ?",
            (int(site),)).fetchone()
        return dict(zip(keys, row)) if row else None

    def construction_change(self, site: int | str, *, since: Optional[str] = None) -> Optional[dict]:
        """
        What one site's readings say was delivered per resource between a
        moment and the latest reading, and how much of that was the
        commander's own.

        The base is the latest reading at or before ``since`` (the earliest
        reading when ``since`` is None or precedes every reading); each
        resource's ``delivered`` is its provided amount at the latest
        reading minus at the base, ``own`` the commander's contributions
        between the two, ``by_others`` the difference. None when the store
        holds no reading of the site.
        """
        if self._conn is None:
            return None
        market_id = int(site)
        latest = self._conn.execute(
            "SELECT obs_id, observed_at FROM construction_reading WHERE market_id = ? "
            "ORDER BY observed_at DESC, obs_id DESC LIMIT 1", (market_id,)).fetchone()
        if latest is None:
            return None
        base = None
        if since:
            base = self._conn.execute(
                "SELECT obs_id, observed_at FROM construction_reading WHERE market_id = ? "
                "AND observed_at <= ? ORDER BY observed_at DESC, obs_id DESC LIMIT 1",
                (market_id, since)).fetchone()
        if base is None:
            base = self._conn.execute(
                "SELECT obs_id, observed_at FROM construction_reading WHERE market_id = ? "
                "ORDER BY observed_at ASC, obs_id ASC LIMIT 1", (market_id,)).fetchone()
        latest_id, until = latest
        base_id, start = base
        now = dict(self._conn.execute(
            "SELECT symbol, provided FROM construction_reading WHERE obs_id = ?", (latest_id,)))
        then = dict(self._conn.execute(
            "SELECT symbol, provided FROM construction_reading WHERE obs_id = ?", (base_id,)))
        own = dict(self._conn.execute(
            "SELECT symbol, SUM(amount) FROM construction_contribution WHERE market_id = ? "
            "AND observed_at > ? AND observed_at <= ? GROUP BY symbol", (market_id, start, until)))
        resources: dict[str, dict] = {}
        for symbol in sorted(set(now) | set(then) | set(own)):
            delivered = int(now.get(symbol) or 0) - int(then.get(symbol) or 0)
            mine = int(own.get(symbol) or 0)
            resources[symbol] = {"delivered": delivered, "own": mine, "by_others": delivered - mine}
        totals = {key: sum(r[key] for r in resources.values())
                  for key in ("delivered", "own", "by_others")}
        return {"site": market_id, "since": start, "until": until,
                "from_first_reading": base_id == self._first_reading_id(market_id),
                "resources": resources, **totals}

    def _first_reading_id(self, market_id: int) -> Optional[int]:
        row = self._conn.execute(
            "SELECT obs_id FROM construction_reading WHERE market_id = ? "
            "ORDER BY observed_at ASC, obs_id ASC LIMIT 1", (market_id,)).fetchone()
        return row[0] if row else None

    def last_publish(self, site: int | str) -> Optional[str]:
        """When this site's block was last published anywhere, as the reading's stamp the ledger kept."""
        if self._conn is None:
            return None
        row = self._conn.execute(
            "SELECT value FROM writes WHERE value LIKE ? ORDER BY written_at DESC LIMIT 1",
            (f"{int(site)}@%",)).fetchone()
        return row[0].split("@", 1)[1] if row else None


# -- a construction block's publish, remembered ---------------------------------------
#
# The two columns a block carries beside the game's numbers -- what was
# delivered since the tool last published it, and how much of that was
# others' -- need the moment of the last publish. The writes ledger keeps
# it: one row per region, its value ``<site>@<stamp of the reading
# published>``. Both the command and `serve` go through these two.

def publish_target(sheet_id: str) -> str:
    return f"gsheet:{sheet_id}"


def change_since_publish(site: int | str, sheet_id: str, tab: str, a1: str) -> Optional[dict]:
    """The site's change since the last publish into this region (or since its first reading). Never raises."""
    from . import writes

    try:
        history = History.open()
        try:
            if not history.available:
                return None
            mark = writes.recorded(publish_target(sheet_id), tab, [a1]).get(a1)
            since = mark.split("@", 1)[1] if mark and "@" in mark else None
            return history.construction_change(site, since=since)
        finally:
            history.close()
    except Exception:                       # the store is additive
        return None


def record_publish(site: int | str, sheet_id: str, tab: str, a1: str, stamp: str) -> bool:
    """Remember that this region now shows the site's reading of ``stamp``."""
    from . import writes

    return writes.record(publish_target(sheet_id), tab, {a1: f"{int(site)}@{stamp}"})


def reading_stamp(moment: Any) -> str:
    """A site's timestamp as the store writes it (whole seconds, Z)."""
    if moment is None:
        return ""
    try:
        from datetime import timezone
        return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (AttributeError, ValueError):
        return str(moment)


def supply(ctx: Any) -> History:
    """The supplier core offers: opens the store on the first pull; the refresh memoises it."""
    return History.open()


def offered() -> dict:
    """Core's own supplier table, merged ahead of every plugin's."""
    return {NAME: supply}
