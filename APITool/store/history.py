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
        """Depot readings of one site, newest first; empty until the journal ingest records them."""
        return self.observations("colonisationconstructiondepot", str(site), limit=limit)


def supply(ctx: Any) -> History:
    """The supplier core offers: opens the store on the first pull; the refresh memoises it."""
    return History.open()


def offered() -> dict:
    """Core's own supplier table, merged ahead of every plugin's."""
    return {NAME: supply}
