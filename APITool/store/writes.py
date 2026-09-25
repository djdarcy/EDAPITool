"""
The writes ledger: what the tool last wrote to each cell, per target.

The rule it serves (#25, slice 4): a cell still holding exactly what the
tool last wrote there is the tool's own and may be refreshed; anything
else belongs to a person. This module is only the memory. The decision
lives in the sheets toolkit (``APITool.sheets.ledger``), which never
touches sqlite; core hands it a :class:`StoreLedger` bound to one target.

Rows are keyed by ``(target, tab, a1)`` -- the target is the NAME the
person gave it in ``config.json``, so two targets on one spreadsheet keep
separate memories. The value stored is what the cell READ BACK as a
formula right after the write, never what was sent: Sheets reinterprets
entered text, and a ledger of what was sent would call the tool's own
cells foreign the first time it did.

The table is primary: ``store rebuild`` never touches it, because a
regenerated ledger would be a forged one.

Like ``archive()``, nothing here raises into its caller. A ledger that
cannot be read answers "nothing recorded", which makes every cell
someone else's -- v0.7.6's behaviour, the safe direction. A ledger that
cannot be written leaves the cells unrecorded, so the next run treats
them the same way. ``ED_NO_STORE`` turns both off.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Iterable, Mapping, Optional

from .. import settings
from . import GUARD_VAR, now_utc, open_store, store_path


def _report(message: str) -> None:
    # Its own once-key: a store failure already reported by archive() must
    # not silence the ledger's, which says something different.
    settings.report_once(store_path().with_name(store_path().name + "#writes"), message)


def recorded(target: str, tab: str, a1s: Iterable[str], *,
             conn: Optional[sqlite3.Connection] = None) -> dict[str, str]:
    """What the tool last wrote to each of ``a1s`` on ``target``'s ``tab``; absent cells omitted."""
    cells = [str(a1) for a1 in a1s]
    if not cells or os.environ.get(GUARD_VAR):
        return {}
    own = conn is None
    try:
        if own:
            conn = open_store()
        out: dict[str, str] = {}
        for start in range(0, len(cells), 500):
            chunk = cells[start:start + 500]
            marks = ",".join("?" * len(chunk))
            rows = conn.execute(
                f"SELECT a1, value FROM writes WHERE target=? AND tab=? AND a1 IN ({marks})",
                (target, tab, *chunk))
            out.update({a1: ("" if value is None else value) for a1, value in rows})
        return out
    except Exception as exc:                      # the store is additive
        _report(f"store: could not read the writes ledger: {exc}")
        return {}
    finally:
        if own and conn is not None:
            conn.close()


def record(target: str, tab: str, values: Mapping[str, str], run_id: Optional[str] = None, *,
           conn: Optional[sqlite3.Connection] = None) -> bool:
    """
    Remember ``values`` (A1 -> what read back) as the tool's last write there.

    Returns whether it was recorded. False is never an error the caller must
    handle: the cells simply stay unrecorded, and the next run holds them.
    """
    if not values or os.environ.get(GUARD_VAR):
        return False
    own = conn is None
    try:
        if own:
            conn = open_store()
        stamp = now_utc()
        with conn:
            conn.executemany(
                "INSERT INTO writes (target, tab, a1, value, written_at, run_id) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(target, tab, a1) DO UPDATE SET "
                "value=excluded.value, written_at=excluded.written_at, run_id=excluded.run_id",
                [(target, tab, str(a1), "" if v is None else str(v), stamp, run_id)
                 for a1, v in values.items()])
        return True
    except Exception as exc:                      # the store is additive
        _report(f"store: could not record what was written: {exc}")
        return False
    finally:
        if own and conn is not None:
            conn.close()


class StoreLedger:
    """The ledger bound to one target: what ``APITool.sheets.ledger`` asks of it."""

    def __init__(self, target: str, run_id: Optional[str] = None):
        self.target = target
        self.run_id = run_id

    def recorded(self, tab: str, a1s: Iterable[str]) -> dict[str, str]:
        return recorded(self.target, tab, a1s)

    def record(self, tab: str, values: Mapping[str, str]) -> bool:
        return record(self.target, tab, values, self.run_id)
